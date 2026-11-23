cmake_minimum_required(VERSION 3.8)
project(localization_case)

find_package(ament_cmake REQUIRED)

install(DIRECTORY launch config rviz DESTINATION share/${PROJECT_NAME})
install(PROGRAMS scripts/measure_localization.py scripts/inspect_recording.py
  DESTINATION lib/${PROJECT_NAME})

if(BUILD_TESTING)
  find_package(ament_cmake_pytest REQUIRED)
  ament_add_pytest_test(measurement test/test_measurement.py TIMEOUT 60)
endif()

ament_package()
