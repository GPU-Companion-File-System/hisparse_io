# Add the repository's public Tutti v0.1.1 benchmark targets to the upstream build.
if(CMAKE_VERSION VERSION_LESS 3.19)
  message(FATAL_ERROR "This consumer hook requires CMake >= 3.19 (DEFER support)")
endif()
find_package(Protobuf REQUIRED)
find_package(CUDAToolkit 12.6 REQUIRED)
get_filename_component(HISPARSE_PROJECT_ROOT "${CMAKE_CURRENT_LIST_DIR}/.." ABSOLUTE)
set(HISPARSE_PROJECT_ROOT "${HISPARSE_PROJECT_ROOT}" CACHE INTERNAL "Benchmark root")
cmake_language(DEFER CALL include "${HISPARSE_PROJECT_ROOT}/cmake/tutti-v011-targets.cmake")
