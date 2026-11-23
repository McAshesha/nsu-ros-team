"""Run only the localization owners; replay supplies clock, odometry and lidar TF."""

from pathlib import Path

from ament_index_python.packages import get_package_share_directory
from launch import LaunchDescription
from launch.actions import DeclareLaunchArgument, OpaqueFunction
from launch.substitutions import LaunchConfiguration
from launch_ros.actions import Node


def localization_nodes(context):
    """Resolve the map to an absolute path before passing it to map_server."""
    params = str(Path(LaunchConfiguration('params_file').perform(context)).resolve())
    map_path = str(Path(LaunchConfiguration('map').perform(context)).resolve())
    if not Path(params).is_file() or not Path(map_path).is_file():
        raise FileNotFoundError('Both params_file and map must name existing files')
    return [
        Node(package='nav2_map_server', executable='map_server', name='map_server',
             parameters=[params, {'yaml_filename': map_path, 'use_sim_time': True}],
             output='screen'),
        Node(package='nav2_amcl', executable='amcl', name='amcl',
             parameters=[params, {'use_sim_time': True}], output='screen'),
        Node(package='nav2_lifecycle_manager', executable='lifecycle_manager',
             name='lifecycle_manager_localization',
             parameters=[params, {'use_sim_time': True}], output='screen'),
    ]


def generate_launch_description():
    """Expose the two inputs while keeping the required node names."""
    share = Path(get_package_share_directory('localization_case'))
    return LaunchDescription([
        DeclareLaunchArgument('params_file', default_value=str(share / 'config/amcl.yaml')),
        DeclareLaunchArgument('map', description='Path to the course-kit map.yaml'),
        OpaqueFunction(function=localization_nodes),
    ])
