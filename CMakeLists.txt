cmake_minimum_required(VERSION 2.8)

project(simple_cpp_program)

add_executable(simple_cpp_program ${PROJECT_SOURCE_DIR}/main.cpp)

if(NOT WIN32)
    target_link_libraries(simple_cpp_program stdc++)
endif()

install(TARGETS simple_cpp_program DESTINATION ${PROJECT_SOURCE_DIR}/packages/)

