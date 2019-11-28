from __future__ import absolute_import, division, print_function

import numpy as np
import tensorflow as tf
from tensorflow.python.keras.layers import Dense
from tensorflow_probability.python.distributions import Independent, Normal

from odin.bay.distribution_layers import (NegativeBinomialDispLayer,
                                          ZINegativeBinomialDispLayer)
from odin.networks import DenseDistribution, Identity
from sisua.models.base import SingleCellModel
from sisua.models.modules import (DenseNetwork, create_encoder_decoder,
                                  get_latent)


class SCVI(SingleCellModel):
  r""" Re-implementation of single cell variational inference (scVI) in
  Tensorflow

  Arguments:
    clip_library : `float` (default=`10000`)
      clipping the maximum library size to prevent overflow in exponential,
      e.g. if L=10 then the maximum library value is softplus(10)=~10

  References:
    Romain Lopez (2018). https://github.com/YosefLab/scVI/tree/master/scvi.

  """

  def __init__(self,
               outputs,
               zdim=32,
               zdist='diag',
               ldist='normal',
               hdim=128,
               nlayers=2,
               xdrop=0.3,
               edrop=0,
               zdrop=0,
               ddrop=0,
               clip_library=1e4,
               batchnorm=True,
               linear_decoder=False,
               **kwargs):
    super(SCVI, self).__init__(outputs=outputs, **kwargs)
    # initialize the autoencoder
    self.encoder_z, self.decoder = create_encoder_decoder(seed=self.seed,
                                                          **locals())
    self.encoder_l = DenseNetwork(n_units=1,
                                  nlayers=1,
                                  activation='relu',
                                  batchnorm=batchnorm,
                                  input_dropout=xdrop,
                                  output_dropout=edrop,
                                  seed=self.seed,
                                  name='EncoderL')
    self.latent = get_latent(zdist, zdim)
    self.library = get_latent(ldist, 1)
    self.clip_library = float(clip_library)
    n_dims = self.posteriors[0].event_shape[0]
    # mean gamma (logits value, applying softmax later)
    self.px_scale = Dense(units=n_dims, activation='linear', name="MeanScale")
    # dropout logits value
    if self.is_zero_inflated:
      self.px_dropout = Dense(n_dims, activation='linear', name="DropoutLogits")
    else:
      self.px_dropout = Identity(name="DropoutLogits")
    # dispersion (NOTE: while this is different implementation, it ensures the
    # same method as scVI, i.e. cell-gene, gene dispersion)
    self.px_r = Dense(n_dims, activation='linear', name='Dispersion')
    # since we feed the params directly, the DenseDistribution parameters won't
    # be used
    self.posteriors[0].trainable = False

  def _call(self, x, lmean, lvar, t, y, mask, training, n_mcmc):
    # applying encoding
    e_z = self.encoder_z(x, training=training)
    e_l = self.encoder_l(x, training=training)
    # latent spaces
    qZ = self.latent(e_z, training=training, n_mcmc=n_mcmc)
    qL = self.library(e_l,
                      training=training,
                      n_mcmc=n_mcmc,
                      prior=Independent(
                          Normal(loc=lmean, scale=tf.math.sqrt(lvar)), 1))
    Z_samples = qZ
    # clipping L value to avoid overflow, softplus(12) = 12
    L_samples = tf.clip_by_value(qL, 0, self.clip_library)
    # decoding the latent
    d = self.decoder(Z_samples, training=training)
    # mean parameterizations
    px_scale = tf.nn.softmax(self.px_scale(d), axis=1)
    px_scale = tf.clip_by_value(px_scale, 1e-8, 1 - 1e-8)
    # NOTE: scVI use exp but we use softplus here
    px_rate = tf.nn.softplus(L_samples) * px_scale
    # dispersion parameterizations
    px_r = self.px_r(d)
    # NOTE: scVI use exp but we use softplus here
    px_r = tf.nn.softplus(px_r)
    # dropout for zero inflation
    px_dropout = self.px_dropout(d)
    # mRNA expression distribution
    # this order is the same as how the parameters are splited in distribution
    # layer
    if self.is_zero_inflated:
      params = tf.concat((px_rate, px_r, px_dropout), axis=-1)
    else:
      params = tf.concat((px_rate, px_r), axis=-1)
    pX = self.posteriors[0](params, training=training, projection=False)
    # for semi-supervised learning
    pY = [p(d, training=training) for p in self.posteriors[1:]]
    return [pX] + pY, (qZ, qL)