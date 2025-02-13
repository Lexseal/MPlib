cmake_minimum_required(VERSION 3.12)
project(mp LANGUAGES CXX)
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_FLAGS_RELEASE " -O3 -g3 -Wall -fsized-deallocation -Wno-deprecated-declarations")
set(CMAKE_C_FLAGS "${CMAKE_C_FLAGS} -O3")
set(CMAKE_CXX_FLAGS "${CMAKE_CXX_FLAGS} -O3")

# Pinocchio uses its own FindCppAD, but does not provide it.
set(CMAKE_MODULE_PATH "${CMAKE_CURRENT_SOURCE_DIR}/CMakeModules")

find_package(Eigen3 3.4.0 REQUIRED)
find_package(Boost COMPONENTS system filesystem REQUIRED)
find_package(ompl REQUIRED)
find_package(fcl REQUIRED)
find_package(pinocchio REQUIRED)
find_package(assimp REQUIRED)
find_package(orocos_kdl REQUIRED)
find_package(urdfdom REQUIRED)

include_directories("/usr/include/eigen3")
include_directories(${OMPL_INCLUDE_DIRS} ${urdfdom_INCLUDE_DIRS})
include_directories("src")

# store libries in a variable
set(LIBS ompl fcl pinocchio assimp orocos-kdl Boost::system Boost::filesystem urdfdom_model urdfdom_world)

file(GLOB_RECURSE PROJECT_SRC "src/*.h" "src/*.cpp" "src/*.hpp")
add_library(mp STATIC ${PROJECT_SRC})
target_link_libraries(mp PRIVATE ${LIBS})
set_target_properties(mp PROPERTIES POSITION_INDEPENDENT_CODE TRUE)

add_subdirectory("third_party/pybind11")
include_directories("python")
pybind11_add_module(pymp python/pybind.cpp)
target_link_libraries(pymp PRIVATE mp)

# compile test_articulated_model and run the test
add_executable(test_articulated_model tests/test_articulated_model.cpp)
target_link_libraries(test_articulated_model PRIVATE mp)
add_test(NAME test_articulated_model COMMAND test_articulated_model)
