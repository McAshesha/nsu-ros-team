from setuptools import find_packages, setup

package_name = 'scene_adapter'

setup(
    name=package_name,
    version='0.0.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml', 'README.md']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Egor Kolosov',
    maintainer_email='kolosovegor06@gmail.com',
    description='Адаптер VLM: SceneDescription v1 в режимах mock, cache и live',
    license='Apache-2.0',
    extras_require={
        'test': [
            'pytest',
        ],
    },
    entry_points={
        'console_scripts': [
            'scene_adapter = scene_adapter.node:main',
        ],
    },
)
