FROM althack/ros2:jazzy-gazebo

USER root

RUN apt-get update && apt-get install -y --no-install-recommends \
    git curl build-essential pciutils mesa-utils vulkan-tools fish \
    ros-jazzy-nav2-amcl ros-jazzy-nav2-map-server \
    ros-jazzy-nav2-lifecycle-manager ros-jazzy-tf2-ros-py ros-jazzy-tf2-tools \
    ros-jazzy-ament-cmake-pytest python3-pytest python3-yaml \
    python3-matplotlib python3-numpy python3-pil \
    && rm -rf /var/lib/apt/lists/*

ENV UV_INSTALL_DIR=/usr/local/bin \
    UV_TOOL_BIN_DIR=/usr/local/bin \
    UV_TOOL_DIR=/opt/uv-tools

RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && uv tool install ruff \
    && uv tool install ty

USER ros
