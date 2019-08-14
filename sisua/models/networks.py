from __future__ import absolute_import, division, print_function

from tensorflow.python.keras import Model, Sequential
from tensorflow.python.keras.layers import (Activation, BatchNormalization,
                                            Dense, Dropout)


class DenseNetwork(Sequential):
  """
  """

  def __init__(self,
               n_units=128,
               n_layers=2,
               activation='relu',
               batchnorm=True,
               input_dropout=0.,
               output_dropout=0,
               seed=8,
               name=None):
    layers = []
    if 0. < input_dropout < 1.:
      layers.append(Dropout(input_dropout, seed=seed))
    for i in range(int(n_layers)):
      layers.append(
          Dense(n_units,
                activation='linear' if batchnorm else activation,
                use_bias=False if batchnorm else True,
                name="DenseLayer%d" % i))
      if batchnorm:
        layers.append(BatchNormalization())
        layers.append(Activation(activation))
    if 0. < output_dropout < 1.:
      layers.append(Dropout(output_dropout, seed=seed))
    super(DenseNetwork, self).__init__(layers=layers, name=name)


class RecurrentNetwork(Model):

  def __init__(self, name=None):
    super(RecurrentNetwork, self).__init__(name=name)
    raise NotImplementedError
