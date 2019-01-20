from matplotlib import pyplot as plt
import seaborn
import pandas as pd

import numpy as np
from scipy.stats import kde, entropy

from odin import backend as K, visual
from odin.visual import plot_series_statistics
from odin.utils import catch_warnings_ignore
from odin.stats import describe, sparsity_percentage

# ===========================================================================
# Some helper
# ===========================================================================
def _mean(W_or_V):
  """ The reconstruction from VAE is returned by:
  (mean, total_stddev, explained_stddev)
  This method will make sure only mean value is return
  """
  W_or_V = (W_or_V[0]
          if isinstance(W_or_V, (tuple, list)) or W_or_V.ndim == 3 else
          W_or_V)
  assert W_or_V.ndim == 2
  return W_or_V


# ===========================================================================
# Series analysis
# ===========================================================================
def _show_zero_inflated_pi(p, ax, handles, indices):
  ax = ax.twinx()
  _, = ax.plot(p[indices],
               marker='o', linestyle='None',
               markersize=0.8, color='blue',
               alpha=0.3, label="$p_{dropout}$")
  ax.set_ylabel("Zero-inflation rate", fontsize=8)
  ax.tick_params(axis='both', labelsize=8)
  handles.append(_)

def plot_countsum_series(original, imputed, p=None,
                         reduce_axis=0, title=None, ax=None):
  """
  x: [n_samples, n_genes]
    original count
  w: tuple (expected, stdev_total, stdev_explained) [n_samples, n_genes]
    the prediction
  p: [n_samples, n_genes]
    dropout probability
  """
  if ax is None:
    ax = visual.to_axis(ax)
  reduce_axis = int(reduce_axis)

  if isinstance(imputed, (tuple, list)): # no statistics provided
    assert len(imputed) == 3
    expected, stdev_total, stdev_explained = imputed
  elif imputed.ndim == 3:
    assert imputed.shape[0] == 3
    expected, stdev_total, stdev_explained = imputed[0], imputed[1], imputed[2]
  else:
    raise ValueError()

  count_sum_observed        = np.log1p(np.sum(original, axis=reduce_axis))
  count_sum_expected        = np.log1p(np.sum(expected, axis=reduce_axis))
  count_sum_stdev_total     = np.log1p(np.sum(stdev_total, axis=reduce_axis))
  count_sum_stdev_explained = np.log1p(np.sum(stdev_explained, axis=reduce_axis))
  if p is not None:
    p_sum = np.mean(p, axis=reduce_axis)

  ax, handles, indices = plot_series_statistics(
      count_sum_observed, count_sum_expected,
      explained_stdev=count_sum_stdev_explained,
      total_stdev=count_sum_stdev_total,
      fontsize=8, ax=ax, legend_enable=False,
      title=title,
      despine=True if p is None else False,
      return_handles=True, return_indices=True,
      xscale='linear', yscale='linear', sort_by='expected')
  if p is not None:
    _show_zero_inflated_pi(p_sum, ax, handles, indices)
  ax.legend(handles=handles, loc='best', markerscale=4, fontsize=8)

# ===========================================================================
# Comparing Gene expression
# ===========================================================================
def plot_countsum_comparison(original, reconstructed, imputed, title,
                             comparing_axis=0, ax=None):
  """
  original : [n_samples, n_genes]
  reconstructed : [n_samples, n_genes]
  imputed : [n_samples, n_genes]
  """
  from matplotlib import pyplot as plt
  ax = visual.to_axis(ax)

  original = original.sum(axis=comparing_axis)
  reconstructed = _mean(reconstructed).sum(axis=comparing_axis)
  imputed = _mean(imputed).sum(axis=comparing_axis)
  assert original.shape == reconstructed.shape == imputed.shape

  sorted_indices = np.argsort(original)

  original = np.log1p(original[sorted_indices])
  reconstructed = np.log1p(reconstructed[sorted_indices])
  imputed = np.log1p(imputed[sorted_indices])

  # ====== plotting the figures ====== #
  colors = seaborn.color_palette(palette='Set2', n_colors=3)

  ax.scatter(original, imputed, c=colors[1], s=3, alpha=0.3)
  ax.scatter(original, reconstructed, c=colors[2], s=3, alpha=0.3)
  # ====== plotting the median line ====== #
  xmin, xmax = ax.get_xlim()
  ymin, ymax = ax.get_ylim()
  max_val = max(xmax, ymax)

  ax.axhline(xmin=0, xmax=max_val, y=np.median(original),
             color=colors[0], linestyle='--', linewidth=1.5,
             label="Corrupted Median")
  ax.axhline(xmin=0, xmax=max_val, y=np.median(imputed),
             color=colors[1], linestyle='--', linewidth=1.5,
             label="Imputed Median")
  ax.axhline(xmin=0, xmax=max_val, y=np.median(reconstructed),
             color=colors[2], linestyle='--', linewidth=1.5,
             label="Reconstructed Median")
  # ====== adjust the aspect ====== #
  visual.plot_aspect(aspect='equal', adjustable='box', ax=ax)
  ax.set_xlim((0, max_val))
  ax.set_ylim((0, max_val))

  ax.plot((0, max_val), (0, max_val),
          color='black', linestyle=':', linewidth=1)
  plt.legend(fontsize=8)
  ax.set_xlabel("Log-Count of the corrupted data")
  ax.set_ylabel("Log-Count of the reconstructed and imputed data")
  ax.set_title(title)

  return ax

# ===========================================================================
# Imputation analysis
# ===========================================================================
def plot_imputation_series(original, imputed, title="Imputation"):
  original = K.log_norm(original, axis=0)
  imputed = K.log_norm(imputed, axis=0)
  max_val = max(np.max(original),
                np.max(imputed))

  with catch_warnings_ignore(FutureWarning):
    grid = seaborn.pairplot(data=pd.DataFrame({'Original Value': original,
                                               'Imputed Value': imputed}),
        height=4, aspect=1,
        kind='reg',
        diag_kws={'bins': 180},
        plot_kws={'scatter_kws': dict(s=2, alpha=0.6),
                  'line_kws': dict(color='red', alpha=0.8),
                  'color': 'g'})
    ids = np.linspace(0, max_val)
    grid.axes[0, 1].set_xlim((0, max_val))
    grid.axes[0, 1].set_ylim((0, max_val))
    grid.axes[0, 1].plot(ids, ids, linestyle='--', linewidth=1, color='black')

    grid.axes[1, 0].set_xlim((0, max_val))
    grid.axes[1, 0].set_ylim((0, max_val))
    grid.axes[1, 0].plot(ids, ids, linestyle='--', linewidth=1, color='black')


def plot_imputation(original, imputed, title="Imputation"):
  """ Original code: scVI """
  y = imputed
  x = original

  ymax = 10
  mask = x < ymax
  x = x[mask]
  y = y[mask]

  mask = y < ymax
  x = x[mask]
  y = y[mask]

  l_minimum = np.minimum(x.shape[0], y.shape[0])

  x = x[:l_minimum]
  y = y[:l_minimum]

  data = np.vstack([x, y])
  plt.figure(figsize=(5, 5))

  axes = plt.gca()
  axes.set_xlim([0, ymax])
  axes.set_ylim([0, ymax])

  nbins = 50

  # Evaluate a gaussian kde on a regular grid of nbins x nbins over data extents
  k = kde.gaussian_kde(data)
  xi, yi = np.mgrid[0:ymax:nbins * 1j, 0:ymax:nbins * 1j]
  zi = k(np.vstack([xi.flatten(), yi.flatten()]))

  plt.title(title, fontsize=12)
  plt.ylabel("Imputed counts")
  plt.xlabel('Original counts')

  plt.pcolormesh(yi, xi, zi.reshape(xi.shape), cmap="Reds")

  a, _, _, _ = np.linalg.lstsq(y[:, np.newaxis], x, rcond=-1)
  linspace = np.linspace(0, ymax)
  plt.plot(linspace, a * linspace, color='black')

  plt.plot(linspace, linspace, color='black', linestyle=":")
