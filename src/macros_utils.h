#pragma once

#include <memory>

#define ASSERT(exp, info)             \
  if (!(exp)) {                       \
    throw std::runtime_error((info)); \
  }

/** @brief Macro that defines a forward declaration for a class, and
    shared pointers to the class.
    For example MPLIB_CLASS_FORWARD(MyType);
    will produce type definitions for MyType and MyTypePtr. */
#define MPLIB_CLASS_FORWARD(C) \
  class C;                     \
  using C##Ptr = std::shared_ptr<C>

/** @brief Macro that defines a forward declaration for a class template, and
    shared pointers to the class template.
    For example MPLIB_CLASS_TEMPLATE_FORWARD(MyTypeTpl);
    will produce type definitions for MyTypeTpl and MyTypeTplPtr. */
#define MPLIB_CLASS_TEMPLATE_FORWARD(C) \
  template <typename S>                 \
  class C;                              \
  template <typename S>                 \
  using C##Ptr = std::shared_ptr<C<S>>

/** @brief Macro that defines a forward declaration for a struct template, and
    shared pointers to the struct template.
    For example MPLIB_STRUCT_TEMPLATE_FORWARD(MyTypeTpl);
    will produce type definitions for MyTypeTpl and MyTypeTplPtr. */
#define MPLIB_STRUCT_TEMPLATE_FORWARD(C) \
  template <typename S>                  \
  struct C;                              \
  template <typename S>                  \
  using C##Ptr = std::shared_ptr<C<S>>
