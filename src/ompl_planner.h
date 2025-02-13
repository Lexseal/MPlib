#pragma once

#include <vector>

#include <ompl/base/State.h>
#include <ompl/base/StateValidityChecker.h>
#include <ompl/base/spaces/RealVectorStateSpace.h>
#include <ompl/base/spaces/SO2StateSpace.h>

/* #include <ompl/base/goals/GoalStates.h> */
/* #include <ompl/base/objectives/StateCostIntegralObjective.h> */
/* #include <ompl/base/samplers/ObstacleBasedValidStateSampler.h> */
/* #include <ompl/geometric/PathSimplifier.h> */
/* #include <ompl/geometric/SimpleSetup.h> */
/* #include <ompl/util/RandomNumbers.h> */

#include "macros_utils.h"
#include "planning_world.h"
#include "types.h"

namespace mplib::ompl {

template <typename S>
std::vector<S> state2vector(const ob::State *const &state_raw,
                            const SpaceInformation *const &si_);

template <typename IN_TYPE, typename OUT_TYPE>
std::vector<OUT_TYPE> eigen2vector(const VectorX<IN_TYPE> &x) {
  std::vector<OUT_TYPE> ret;
  for (size_t i = 0; i < static_cast<size_t>(x.rows()); i++)
    ret.push_back(static_cast<OUT_TYPE>(x[i]));
  return ret;
}

template <typename IN_TYPE, typename OUT_TYPE>
VectorX<OUT_TYPE> vector2eigen(const std::vector<IN_TYPE> &x) {
  VectorX<OUT_TYPE> ret(x.size());
  for (size_t i = 0; i < x.size(); i++) ret[i] = static_cast<OUT_TYPE>(x[i]);
  return ret;
}

template <typename S>
VectorX<S> state2eigen(const ob::State *const &state_raw,
                       const SpaceInformation *const &si_) {
  auto vec_ret = state2vector<S>(state_raw, si_);
  auto ret = vector2eigen<S, S>(vec_ret);
  return ret;
}

// ValidityCheckerTplPtr
MPLIB_CLASS_TEMPLATE_FORWARD(ValidityCheckerTpl);

template <typename S>
class ValidityCheckerTpl : public ob::StateValidityChecker {
 public:
  ValidityCheckerTpl(const PlanningWorldTplPtr<S> &world, const SpaceInformationPtr &si)
      : ob::StateValidityChecker(si), world_(world) {}

  bool isValid(const ob::State *state_raw) const {
    world_->setQposAll(state2eigen<S>(state_raw, si_));
    return !world_->collide();
  }

  /**
   * @brief Report the distance to the nearest invalid state when starting from
   *  state. If the distance is negative, the value of clearance is the
   *  penetration depth.
   */
  double clearance(const ob::State *state_raw) const {
    world_->setQposAll(state2eigen<S>(state_raw, si_));
    return static_cast<double>(world_->distance());
  }

  bool _isValid(const VectorX<S> &state) const {
    world_->setQposAll(state);
    return !world_->collide();
  }

 private:
  PlanningWorldTplPtr<S> world_;
};

// Common Type Alias ==========================================================
using ValidityCheckerf = ValidityCheckerTpl<float>;
using ValidityCheckerd = ValidityCheckerTpl<double>;
using ValidityCheckerfPtr = ValidityCheckerTplPtr<float>;
using ValidityCheckerdPtr = ValidityCheckerTplPtr<double>;

// OMPLPlannerTplPtr
MPLIB_CLASS_TEMPLATE_FORWARD(OMPLPlannerTpl);

template <typename S>
class OMPLPlannerTpl {
 public:
  OMPLPlannerTpl(const PlanningWorldTplPtr<S> &world);

  const PlanningWorldTplPtr<S> &get_world() const { return world_; }

  size_t get_dim() const { return dim_; }

  VectorX<S> random_sample_nearby(const VectorX<S> &start_state) const;

  std::pair<std::string, MatrixX<S>> plan(
      const VectorX<S> &start_state, const std::vector<VectorX<S>> &goal_states,
      const std::string &planner_name = "RRTConnect", double time = 1.0,
      double range = 0.0, double goal_bias = 0.05, double pathlen_obj_weight = 10.0,
      bool pathlen_obj_only = false, bool verbose = false) const;

 private:
  CompoundStateSpacePtr cs_;
  SpaceInformationPtr si_;
  ProblemDefinitionPtr pdef_;
  PlanningWorldTplPtr<S> world_;
  ValidityCheckerTplPtr<S> valid_checker_;
  size_t dim_;
  std::vector<S> lower_joint_limits_, upper_joint_limits_;
  std::vector<bool> is_revolute_;

  void build_state_space();
};

// Common Type Alias ==========================================================
using OMPLPlannerTplf = OMPLPlannerTpl<float>;
using OMPLPlannerTpld = OMPLPlannerTpl<double>;
using OMPLPlannerTplfPtr = OMPLPlannerTplPtr<float>;
using OMPLPlannerTpldPtr = OMPLPlannerTplPtr<double>;

// Explicit Template Instantiation Declaration ================================
#define DECLARE_TEMPLATE_OMPL_PLANNER(S)                                              \
  extern template std::vector<S> state2vector<S>(const ob::State *const &state_raw,   \
                                                 const SpaceInformation *const &si_); \
  extern template class ValidityCheckerTpl<S>;                                        \
  extern template class OMPLPlannerTpl<S>

DECLARE_TEMPLATE_OMPL_PLANNER(float);
DECLARE_TEMPLATE_OMPL_PLANNER(double);

}  // namespace mplib::ompl
