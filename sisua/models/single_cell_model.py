from __future__ import absolute_import, division, print_function

import inspect
import multiprocessing as mpi
import os
import string
from abc import ABCMeta, abstractmethod, abstractproperty
from collections import OrderedDict, defaultdict
from functools import partial
from typing import Iterable, List, Text, Union

import numpy as np
import tensorflow as tf
from six import add_metaclass, string_types
from tensorflow import keras
from tensorflow.python.data import Dataset
from tensorflow.python.data.ops.dataset_ops import DatasetV2
from tensorflow.python.keras.callbacks import (Callback, CallbackList,
                                               LambdaCallback,
                                               LearningRateScheduler,
                                               ModelCheckpoint)
from tensorflow.python.platform import tf_logging as logging
from tqdm import tqdm

from odin.backend import interpolation
from odin.backend.keras_callbacks import EarlyStopping
from odin.backend.keras_helpers import layer2text
from odin.bay import RandomVariable
from odin.bay.distributions import concat_distribution
from odin.bay.vi import BetaVAE
from odin.networks import NetworkConfig
from odin.utils import (cache_memory, catch_warnings_ignore, classproperty,
                        is_primitive)
from odin.visual import Visualizer
from sisua.data import OMIC, SingleCellOMIC

__all__ = ['SingleCellModel', 'NetworkConfig', 'RandomVariable', 'interpolation']


def _to_data(x, batch_size=64) -> Dataset:
  if isinstance(x, SingleCellOMIC):
    inputs = x.create_dataset(batch_size=batch_size)
  elif isinstance(x, DatasetV2):
    inputs = x
  # given numpy ndarrays
  else:
    x = tf.nest.flatten(x)
    inputs = SingleCellOMIC(x[0])
    if len(x) > 1:
      omics = list(OMIC)
      # we don't know what is the omic of data anyway, random assigning it
      for arr, om_random in zip(x[1:], omics[1:]):
        inputs.add_omic(omic=om_random, X=arr)
    inputs = inputs.create_dataset(inputs.omics, batch_size=batch_size)
  return inputs


# ===========================================================================
# SingleCell model
# ===========================================================================
class SingleCellModel(BetaVAE, Visualizer):
  r"""
  Note:
    It is recommend to call `tensorflow.random.set_seed` for reproducible
    results.
  """

  def __init__(
      self,
      outputs: RandomVariable,
      latents: RandomVariable = RandomVariable(10, 'diag', True, 'Latents'),
      encoder: NetworkConfig = NetworkConfig([64, 64],
                                             batchnorm=True,
                                             input_dropout=0.3),
      decoder: NetworkConfig = NetworkConfig([64, 64], batchnorm=True),
      analytic=True,
      log_norm=True,
      beta=1.0,
      name=None,
      **kwargs,
  ):
    super().__init__(outputs=outputs,
                     latents=latents,
                     encoder=encoder,
                     decoder=decoder,
                     beta=beta,
                     name=name,
                     **kwargs)
    self._analytic = bool(analytic)
    self._log_norm = bool(log_norm)
    self._dataset = None
    self._n_inputs = max(len(l.inputs) for l in tf.nest.flatten(self.encoder))

  @property
  def dataset(self):
    r""" Return the name of the last SingleCellOMIC dataset fitted on """
    return self._dataset

  @property
  def log_norm(self):
    return self._log_norm

  @property
  def is_zero_inflated(self):
    return self.posteriors[0].is_zero_inflated

  @classproperty
  def is_multiple_outputs(self):
    r""" Return true if __init__ contains both 'rna_dim' and 'adt_dim'
    as arguments """
    args = inspect.getfullargspec(self.__init__).args
    return 'rna_dim' in args and 'adt_dim' in args

  def encode(self,
             inputs,
             library=None,
             training=None,
             mask=None,
             sample_shape=()):
    if self.log_norm:
      if tf.is_tensor(inputs):
        inputs = tf.math.log1p(inputs)
      else:
        inputs = tf.nest.flatten(inputs)
        inputs[0] = tf.math.log1p(inputs[0])
    # just limit the number of inputs
    if isinstance(inputs, (tuple, list)):
      inputs = inputs[:self._n_inputs]
    return super().encode(inputs=inputs,
                          training=training,
                          mask=mask,
                          sample_shape=sample_shape)

  def decode(self, latents, training=None, mask=None, sample_shape=()):
    return super().decode(latents=latents,
                          training=training,
                          mask=mask,
                          sample_shape=sample_shape)

  def predict(self, inputs, sample_shape=(), batch_size=64, verbose=True):
    r"""
    Return:
      X : `Distribution` or tuple of `Distribution`
        output distribution, multiple distribution is return in case of
        multiple outputs
      Z : `Distribution` or tuple of `Distribution`
        latent distribution, multiple distribution is return in case of
        multiple latents
    """
    inputs = _to_data(inputs, batch_size=batch_size)
    ## making predictions
    X, Z = [], []
    prog = tqdm(inputs, desc="Predicting", disable=not bool(verbose))
    for data in prog:
      pX_Z, qZ_X = self(**data, training=False, sample_shape=sample_shape)
      X.append(pX_Z)
      Z.append(qZ_X)
    prog.clear()
    prog.close()
    # merging the batch distributions
    if isinstance(pX_Z, (tuple, list)):
      merging_axis = 0 if pX_Z[0].batch_shape.ndims == 1 else 1
    else:
      merging_axis = 0 if pX_Z.batch_shape.ndims == 1 else 1
    # multiple outputs
    if isinstance(X[0], (tuple, list)):
      X = tuple([
          concat_distribution([x[idx] for x in X], \
                              axis=merging_axis,
                              name=self.posteriors[idx].name)
          for idx in range(len(X[0]))
      ])
    # single output
    else:
      X = concat_distribution(X,
                              axis=merging_axis,
                              name=self.posteriors[0].name)
    # multiple latents
    if isinstance(Z[0], (tuple, list)):
      Z = tuple([
          concat_distribution([z[idx]
                               for z in Z], axis=0)
          for idx in range(len(Z[0]))
      ])
    else:
      Z = concat_distribution(Z, axis=0)
    return X, Z

  def fit(
      self,
      train: Union[SingleCellOMIC, DatasetV2],
      valid: Union[SingleCellOMIC, DatasetV2] = None,
      valid_freq=500,
      valid_interval=0,
      optimizer='adam',
      learning_rate=1e-3,
      clipnorm=100,
      epochs=-1,
      max_iter=1000,
      sample_shape=(),  # for ELBO
      analytic=None,  # for ELBO
      callback=None,
      compile_graph=True,
      autograph=False,
      logging_interval=2,
      skip_fitted=False,
      log_path=None,
      earlystop_threshold=0.001,
      earlystop_progress_length=0,
      earlystop_patience=-1,
      earlystop_min_epoch=-np.inf,
      terminate_on_nan=True,
      checkpoint=None,
      allow_rollback=False,
      allow_none_gradients=False):
    r""" This fit function is the combination of both
    `Model.compile` and `Model.fit` """
    if analytic is None:
      analytic = self._analytic
    ## preprocessing the data
    if isinstance(train, SingleCellOMIC):
      self._dataset = train.name
    train = _to_data(train)
    if valid is not None:
      valid = _to_data(valid)
    ## call fit
    kw = locals()
    del kw['self']
    args = inspect.getfullargspec(super().fit).args
    for k in list(kw.keys()):
      if k not in args:
        del kw[k]
    return super().fit(**kw)

  @classproperty
  def id(cls):
    class_name = cls.__name__
    name = ''
    for i in class_name:
      if i.isupper():
        name += i
    return name.lower()
