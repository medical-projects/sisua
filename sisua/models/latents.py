from __future__ import absolute_import, division, print_function

from typing import Type

import tensorflow as tf
from tensorflow_probability.python.distributions import (MultivariateNormalDiag,
                                                         Normal)

from odin.bay.distribution_layers import MultivariateNormalLayer, NormalLayer
from odin.networks import DistributionDense


class NormalDiagLatent(DistributionDense):

  def __init__(self, units, use_bias=True, name="LatentSpace"):
    super(NormalDiagLatent, self).__init__(
        units=units,
        posterior=MultivariateNormalLayer(event_size=units,
                                          covariance_type='diag',
                                          softplus_scale=True),
        prior=MultivariateNormalDiag(loc=tf.zeros(shape=units),
                                     scale_identity_multiplier=1),
        use_bias=use_bias,
        name=name)


class NormalLatent(DistributionDense):

  def __init__(self, units, use_bias=True, name="LatentSpace"):
    super(NormalLatent,
          self).__init__(units=units,
                         posterior=NormalLayer(event_shape=units,
                                               softplus_scale=True),
                         prior=Normal(loc=tf.zeros(shape=units),
                                      scale=tf.ones(shape=units)),
                         use_bias=use_bias,
                         name=name)


class MixedNormalLatent(DistributionDense):
  pass


class DirichletLatent(DistributionDense):
  pass


# ===========================================================================
# Helpers
# ===========================================================================
_latent_map = {
    'normal': NormalLatent,
    'diag': NormalDiagLatent,
    'mixed': MixedNormalLatent,
    'diri': DirichletLatent
}


def get_latent(name):
  name = str(name).lower()
  if name not in _latent_map:
    raise ValueError("Only support following latent: %s; but given: '%s'" %
                     (', '.join(_latent_map.keys()), name))
  return _latent_map[name]
