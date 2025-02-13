#include "articulated_model.h"

#include <algorithm>

#include "macros_utils.h"

namespace mplib {

// Explicit Template Instantiation Definition =================================
#define DEFINE_TEMPLATE_ARTICULATED_MODEL(S) template class ArticulatedModelTpl<S>

DEFINE_TEMPLATE_ARTICULATED_MODEL(float);
DEFINE_TEMPLATE_ARTICULATED_MODEL(double);

template <typename S>
ArticulatedModelTpl<S>::ArticulatedModelTpl(const std::string &urdf_filename,
                                            const std::string &srdf_filename,
                                            const Vector3<S> &gravity,
                                            const std::vector<std::string> &joint_names,
                                            const std::vector<std::string> &link_names,
                                            bool verbose, bool convex)
    : pinocchio_model_(
          std::make_shared<PinocchioModelTpl<S>>(urdf_filename, gravity, verbose)),
      fcl_model_(std::make_shared<FCLModelTpl<S>>(urdf_filename, verbose, convex)),
      verbose_(verbose) {
  user_link_names_ =
      link_names.size() == 0 ? pinocchio_model_->getLinkNames(false) : link_names;
  user_joint_names_ =
      joint_names.size() == 0 ? pinocchio_model_->getJointNames(false) : joint_names;
  pinocchio_model_->setLinkOrder(user_link_names_);
  pinocchio_model_->setJointOrder(user_joint_names_);
  fcl_model_->setLinkOrder(user_link_names_);
  fcl_model_->removeCollisionPairsFromSRDF(srdf_filename);
  current_qpos_ = VectorX<S>::Constant(pinocchio_model_->getModel().nv, 0);
  setMoveGroup(user_link_names_);
}

template <typename S>
std::unique_ptr<ArticulatedModelTpl<S>> ArticulatedModelTpl<S>::createFromURDFString(
    const std::string &urdf_string, const std::string &srdf_string,
    const std::vector<std::pair<std::string, std::vector<fcl::CollisionObjectPtr<S>>>>
        &collision_links,
    const Vector3<S> &gravity, const std::vector<std::string> &joint_names,
    const std::vector<std::string> &link_names, bool verbose) {
  auto articulation = std::make_unique<ArticulatedModelTpl<S>>(Secret());

  auto pinocchio_model = articulation->pinocchio_model_ =
      pinocchio::PinocchioModelTpl<S>::createFromURDFString(urdf_string, gravity,
                                                            verbose);
  auto fcl_model = articulation->fcl_model_ =
      fcl::FCLModelTpl<S>::createFromURDFString(urdf_string, collision_links, verbose);
  articulation->verbose_ = verbose;

  auto user_link_names = articulation->user_link_names_ =
      link_names.size() == 0 ? pinocchio_model->getLinkNames(false) : link_names;
  auto user_joint_names = articulation->user_joint_names_ =
      joint_names.size() == 0 ? pinocchio_model->getJointNames(false) : joint_names;
  pinocchio_model->setLinkOrder(user_link_names);
  pinocchio_model->setJointOrder(user_joint_names);
  fcl_model->setLinkOrder(user_link_names);
  fcl_model->removeCollisionPairsFromSRDFString(srdf_string);
  articulation->current_qpos_ =
      VectorX<S>::Constant(pinocchio_model->getModel().nv, 0);
  articulation->setMoveGroup(user_link_names);

  return articulation;
}

template <typename S>
std::vector<std::string> ArticulatedModelTpl<S>::getMoveGroupJointNames() const {
  std::vector<std::string> ret;
  for (auto i : move_group_user_joints_) ret.push_back(user_joint_names_[i]);
  return ret;
}

template <typename S>
void ArticulatedModelTpl<S>::setMoveGroup(const std::string &end_effector) {
  std::vector<std::string> end_effectors = {end_effector};
  setMoveGroup(end_effectors);
}

template <typename S>
void ArticulatedModelTpl<S>::setMoveGroup(
    const std::vector<std::string> &end_effectors) {
  move_group_end_effectors_ = end_effectors;
  move_group_user_joints_ = {};
  for (auto end_effector : end_effectors) {
    auto joint_i = pinocchio_model_->getChainJointIndex(end_effector);
    move_group_user_joints_.insert(move_group_user_joints_.begin(), joint_i.begin(),
                                   joint_i.end());
  }
  std::sort(move_group_user_joints_.begin(), move_group_user_joints_.end());
  auto end_unique =
      std::unique(move_group_user_joints_.begin(), move_group_user_joints_.end());
  move_group_user_joints_.erase(end_unique, move_group_user_joints_.end());
  qpos_dim_ = 0;
  for (auto i : move_group_user_joints_) qpos_dim_ += pinocchio_model_->getJointDim(i);
}

template <typename S>
void ArticulatedModelTpl<S>::setQpos(const VectorX<S> &qpos, bool full) {
  if (full)
    current_qpos_ = qpos;
  else {
    ASSERT(static_cast<size_t>(qpos.size()) == qpos_dim_,
           "Length is not correct, Dim of Q: " + std::to_string(qpos_dim_) +
               " ,Len of qpos: " + std::to_string(qpos.size()));
    size_t len = 0;
    for (auto i : move_group_user_joints_) {
      auto start_idx = pinocchio_model_->getJointId(i),
           dim_i = pinocchio_model_->getJointDim(i);
      for (size_t j = 0; j < dim_i; j++) current_qpos_[start_idx + j] = qpos[len++];
    }
  }
  pinocchio_model_->computeForwardKinematics(current_qpos_);
  // std::cout << "current_qpos " << current_qpos << std::endl;
  std::vector<Transform3<S>> link_pose;
  for (size_t i = 0; i < user_link_names_.size(); i++) {
    Vector7<S> pose_i = pinocchio_model_->getLinkPose(i);
    Transform3<S> tmp_i;
    tmp_i.linear() = Quaternion<S>(pose_i[3], pose_i[4], pose_i[5], pose_i[6]).matrix();
    tmp_i.translation() = pose_i.head(3);
    // std::cout << pose_i << std::endl;
    link_pose.push_back(tmp_i);
  }
  fcl_model_->updateCollisionObjects(link_pose);
}

}  // namespace mplib
