"""ROS-нода scene_adapter: публикует SceneDescription v1 на /perception/scene."""

import rclpy
from rclpy.clock import Clock, ClockType
from rclpy.executors import ExternalShutdownException
from rclpy.node import Node
from robotics_course_interfaces.msg import SceneDescription
from scene_adapter import contract
from scene_adapter.adapter import fixture_backend, parse_config, SceneAdapter
from sensor_msgs.msg import Image


class SceneAdapterNode(Node):

    def __init__(self, **kwargs):
        super().__init__('scene_adapter', **kwargs)
        declare = self.declare_parameter
        mode = declare('mode', 'mock').value
        schema_path = declare('schema_path', 'contracts/scene-description-v1.schema.json').value
        backend_path = declare('backend_fixture', '').value
        self.adapter = SceneAdapter(
            mode=mode,
            validator=contract.load_validator(schema_path),
            abstain_threshold=declare('abstain_threshold', 0.5).value,
            max_age_s=declare('max_age_s', 0.25).value,
            fixture_path=declare('fixture_path', 'fixtures/vlm/scene-clear.json').value,
            cache_dir=declare('cache_dir', '/tmp/scene_adapter_cache').value,
            prompt_path=declare('prompt_path', 'config/scene-prompt.txt').value,
            model_id=declare('model_id', '').value,
            generation_config=parse_config(declare('generation_config', '{}').value),
            # единственный backend без сети — сохранённый ответ из файла
            backend=fixture_backend(backend_path) if backend_path else None,
        )
        self.publisher = self.create_publisher(SceneDescription, '/perception/scene', 10)
        if mode == 'mock':
            # steady-таймер не останавливается при замороженном /clock,
            # а возраст сцены считается по ROS-часам
            self.timer = self.create_timer(
                0.2, self.on_tick, clock=Clock(clock_type=ClockType.STEADY_TIME))
        else:
            self.image_sub = self.create_subscription(
                Image, '/camera/image_raw', self.on_image, 1)
        self.get_logger().info(f'scene_adapter: mode={mode}')

    def now_s(self):
        return self.get_clock().now().nanoseconds / 1e9

    def clock_ready(self):
        # с use_sim_time до первого /clock время равно нулю
        return not self.get_parameter('use_sim_time').value or self.now_s() > 0.0

    def on_tick(self):
        if self.clock_ready():
            self.publish(self.adapter.describe(self.now_s()))

    def on_image(self, msg):
        if not self.clock_ready():
            return
        try:
            scene = self.adapter.describe(self.now_s(), bytes(msg.data))
        except RuntimeError as error:
            self.get_logger().error(str(error))
            return
        self.publish(scene)

    def publish(self, scene):
        self.publisher.publish(contract.scene_to_msg(scene, self.adapter.validator))


def main():
    rclpy.init()
    try:
        node = SceneAdapterNode()
    except (RuntimeError, ValueError, OSError) as error:
        print(f'scene_adapter: {error}')
        rclpy.try_shutdown()
        raise SystemExit(1)
    try:
        rclpy.spin(node)
    except (KeyboardInterrupt, ExternalShutdownException):
        pass
    finally:
        node.destroy_node()
        rclpy.try_shutdown()


if __name__ == '__main__':
    main()
