#!/usr/bin/env python3
"""Draw recorded laser endpoints in map coordinates and actual AMCL covariance."""

import json
from pathlib import Path

import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import numpy as np
from PIL import Image
import yaml


def main():
    folder = Path('evidence/pr08')
    observations = json.loads((folder / 'localization.observations.json').read_text())
    result = json.loads((folder / 'localization.json').read_text())
    metadata = yaml.safe_load((folder / 'map.yaml').read_text())
    image = np.asarray(Image.open(folder / metadata['image']))
    origin = metadata['origin']
    resolution = metadata['resolution']
    height, width = image.shape
    poses = observations['poses']
    fig, axes = plt.subplots(2, 1, figsize=(11, 8), constrained_layout=True,
                             gridspec_kw={'height_ratios': [1.5, 1]})
    ax = axes[0]
    ax.imshow(image, cmap='gray', vmin=0, vmax=254, origin='upper',
              extent=(origin[0], origin[0] + width * resolution,
                      origin[1], origin[1] + height * resolution))
    if not observations['scan_overlays']:
        raise RuntimeError('No exact-time scan transforms were captured; cannot draw an overlay')
    for i, scan in enumerate(observations['scan_overlays']):
        points = np.asarray(scan['points'])
        ax.scatter(points[:, 0], points[:, 1], s=3, alpha=0.55,
                   label=f"Лидар: t={scan['stamp_s']:.1f} с")
    ax.plot([p['x'] for p in poses], [p['y'] for p in poses], color='#0057b8',
             linewidth=2, label='Оценка положения AMCL')
    ax.set(xlabel='x, м', ylabel='y, м', aspect='equal',
           title='ПР08: карта и точки лидара после преобразования TF на время скана')
    ax.legend(loc='upper center', bbox_to_anchor=(0.5, -0.16), ncol=3, fontsize=8)
    ax = axes[1]
    t0 = observations['first_clock_s']
    ax.plot([p['stamp_s'] - t0 for p in poses],
             [p['xy_covariance_m2'] for p in poses], color='#0057b8', linewidth=1.5)
    ax.axvspan(10, 30, alpha=0.1, color='green', label='Окно измерения [10; 30) с')
    ax.axhline(0.25, color='#bd2d28', linestyle='--', label='Порог 0,25 м²')
    median = result['evaluation']['median_xy_covariance_m2']
    availability = result['evaluation']['tf_availability']
    ax.set(xlabel='Время от первого /clock, с', ylabel='cov(x) + cov(y), м²',
           title=f'Медиана = {median:.5f} м²; доступность map → odom = {availability:.0%}')
    ax.grid(alpha=0.2)
    ax.legend(loc='upper right', fontsize=8)
    fig.savefig(folder / 'localization.png', dpi=170)
    plt.close(fig)


if __name__ == '__main__':
    main()
