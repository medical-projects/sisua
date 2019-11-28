from __future__ import absolute_import, division, print_function

import inspect

import tensorflow as tf

from odin.networks import Identity
from sisua.models.base import SingleCellModel
from sisua.models.modules import create_encoder_decoder, get_latent


class VariationalAutoEncoder(SingleCellModel):
  """ Variational Auto Encoder """

  def __init__(self,
               outputs,
               zdim=32,
               zdist='diag',
               hdim=128,
               nlayers=2,
               xdrop=0.3,
               edrop=0,
               zdrop=0,
               ddrop=0,
               batchnorm=True,
               linear_decoder=False,
               **kwargs):
    super().__init__(outputs, **kwargs)
    self.encoder, self.decoder = create_encoder_decoder(seed=self.seed,
                                                        **locals())
    self.latent = get_latent(zdist, zdim)

  def _call(self, x, lmean, lvar, t, y, mask, training, n_mcmc):
    # applying encoding
    e = self.encoder(x, training=training)
    # latent distribution
    qZ = self.latent(e, training=training, n_mcmc=n_mcmc)
    # decoding the latent
    d = self.decoder(qZ, training=training)
    pX = [p(d, training=training) for p in self.posteriors]
    return pX, qZ
