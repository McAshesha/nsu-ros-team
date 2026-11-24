from glob import glob

from setuptools import find_packages, setup

package_name = 'perception_baseline'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'README.md']),
        ('share/' + package_name + '/config', glob('config/*.json')),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Egor Kolosov',
    maintainer_email='kolosovegor06@gmail.com',
    description='Baseline-детектор ПР09: 2D-детекции, точка по глубине и диагностика',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'perception_node = perception_baseline.perception_node:main',
            'send_pair = perception_baseline.send_pair:main',
        ],
    },
)
