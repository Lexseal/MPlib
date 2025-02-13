from __future__ import annotations

import os
from typing import Sequence, Union

import numpy as np
from sapien import Entity, Pose, Scene
from sapien.physx import (
    PhysxArticulation,
    PhysxArticulationLinkComponent,
    PhysxCollisionShapeBox,
    PhysxCollisionShapeCapsule,
    PhysxCollisionShapeConvexMesh,
    PhysxCollisionShapeCylinder,
    PhysxCollisionShapePlane,
    PhysxCollisionShapeSphere,
    PhysxCollisionShapeTriangleMesh,
    PhysxRigidBaseComponent,
)
from transforms3d.euler import euler2quat

from ..planner import Planner
from ..pymp.articulation import ArticulatedModel
from ..pymp.fcl import (
    Box,
    BVHModel,
    Capsule,
    CollisionObject,
    Convex,
    Cylinder,
    Halfspace,
    Sphere,
    collide,
    distance,
)
from ..pymp.ompl import OMPLPlanner
from ..pymp.planning_world import (
    PlanningWorld,
    WorldCollisionResult,
    WorldDistanceResult,
)
from .srdf_exporter import export_srdf
from .urdf_exporter import export_kinematic_chain_urdf


class SapienPlanningWorld(PlanningWorld):
    def __init__(
        self, sim_scene: Scene, planned_articulation_names: list[str] = ["robot"]
    ):
        """
        Creates an mplib.pymp.planning_world.PlanningWorld from a sapien.Scene.

        :param planned_articulation_names: name of planned articulations.
        """
        super().__init__([], [])
        self._sim_scene = sim_scene
        self._multi_shapes_objs = {}  # FIXME: make mplib compatible

        articulations: list[PhysxArticulation] = sim_scene.get_all_articulations()
        actors: list[Entity] = sim_scene.get_all_actors()

        assert (
            len(articulations) <= 1
        ), f"Currently only support 1 articulation, got {len(articulations)}"
        for articulation in articulations:
            urdf_str = export_kinematic_chain_urdf(articulation)
            srdf_str = export_srdf(articulation)

            # Get all links with collision shapes at local_pose
            collision_links = []  # [(link_name, [CollisionObject, ...]), ...]
            for link in articulation.links:
                col_objs = self.convert_sapien_col_shape(link)
                if len(col_objs) > 0:
                    collision_links.append((link.name, col_objs))

            articulated_model = ArticulatedModel.create_from_urdf_string(
                urdf_str,
                srdf_str,
                collision_links=collision_links,
                gravity=[0, 0, -9.81],
                joint_names=[j.name for j in articulation.active_joints],
                link_names=[l.name for l in articulation.links],
                verbose=False,
            )
            articulated_model.set_qpos(articulation.qpos)  # set_qpos to update poses

            # currently only support one single planned articulation.
            # Moreover, the default name is "robot"
            self.add_articulation("robot", articulated_model)

        for articulation_name in planned_articulation_names:
            self.set_articulation_planned(articulation_name, True)

        for entity in actors:
            component = entity.find_component_by_type(PhysxRigidBaseComponent)
            assert (
                component is not None
            ), f"No PhysxRigidBaseComponent found in {entity.name}: {entity.components=}"
            assert not isinstance(
                component, PhysxArticulationLinkComponent
            ), f"Component should not be PhysxArticulationLinkComponent: {component=}"

            # Convert collision shapes at current global pose
            col_objs = self.convert_sapien_col_shape(component)
            if entity.name == "ground" and len(col_objs) == 0:
                print("\x1b[33;1m[Warning] Ignoring ground\x1b[0m")
                continue
            assert len(col_objs) >= 1, (
                f"Should have 1+ collision object, got {len(col_objs)} shapes for "
                f"entity '{entity.name}'"
            )
            # TODO: multiple collision shapes
            # assert len(col_objs) == 1, (
            #     f"Should only have 1 collision object, got {len(col_objs)} shapes for "
            #     f"entity '{entity.name}'"
            # )
            if len(col_objs) > 1:
                self._multi_shapes_objs[entity.name] = col_objs
                for i, col_obj in enumerate(col_objs):
                    self.add_normal_object(f"{entity.name}_{i}", col_obj)
            else:
                self.add_normal_object(entity.name, col_objs[0])

    def update_from_simulation(self, update_attached_object: bool = True) -> None:
        """Updates planning_world articulations/objects pose with current Scene state

        :param update_attached_object: whether to update the attached pose of
                                       all attached objects
        """
        for articulation in self._sim_scene.get_all_articulations():
            # set_qpos to update poses
            self.get_articulation(articulation.name).set_qpos(articulation.qpos)

        for entity in self._sim_scene.get_all_actors():
            component = entity.find_component_by_type(PhysxRigidBaseComponent)
            assert (
                component is not None
            ), f"No PhysxRigidBaseComponent found in {entity.name}: {entity.components=}"
            assert not isinstance(
                component, PhysxArticulationLinkComponent
            ), f"Component should not be PhysxArticulationLinkComponent: {component=}"

            shapes = component.collision_shapes
            assert len(shapes) >= 1, (
                f"Should have 1+ collision shape, got {len(shapes)} shapes for "
                f"entity '{entity.name}'"
            )
            # TODO: multiple collision shapes
            # assert len(shapes) == 1, (
            #     f"Should only have 1 collision shape, got {len(shapes)} shapes for "
            #     f"entity '{entity.name}'"
            # )
            if len(shapes) > 1:
                for i, (shape, col_obj) in enumerate(
                    zip(shapes, self._multi_shapes_objs[entity.name])
                ):
                    pose: Pose = entity.pose * shape.local_pose
                    # NOTE: Convert poses for Capsule/Cylinder
                    if isinstance(
                        shape, (PhysxCollisionShapeCapsule, PhysxCollisionShapeCylinder)
                    ):
                        pose = pose * Pose(q=euler2quat(0, np.pi / 2, 0))
                    col_obj.set_transformation(np.hstack((pose.p, pose.q)))
                continue

            shape = shapes[0]

            pose: Pose = entity.pose * shape.local_pose
            # NOTE: Convert poses for Capsule/Cylinder
            if isinstance(
                shape, (PhysxCollisionShapeCapsule, PhysxCollisionShapeCylinder)
            ):
                pose = pose * Pose(q=euler2quat(0, np.pi / 2, 0))

            # handle attached object
            if self.is_normal_object_attached(entity.name):
                attached_body = self.get_attached_object(entity.name)
                if update_attached_object:
                    parent_posevec = (
                        attached_body.get_attached_articulation()
                        .get_pinocchio_model()
                        .get_link_pose(attached_body.get_attached_link_id())
                    )
                    parent_pose = Pose(parent_posevec[:3], parent_posevec[3:])
                    pose = parent_pose.inv() * pose  # new attached pose
                    attached_body.set_pose(np.hstack((pose.p, pose.q)))
                attached_body.update_pose()
            else:
                self.get_normal_object(entity.name).set_transformation(
                    np.hstack((pose.p, pose.q))
                )

    def _get_col_obj(
        self,
        obj: PhysxArticulation | PhysxArticulationLinkComponent | Entity,
    ) -> list[CollisionObject] | CollisionObject | ArticulatedModel | None:
        """Helper function to get mplib collision object from sapien object"""
        if isinstance(obj, PhysxArticulation):
            return self.get_articulation(obj.name)
        elif isinstance(obj, Entity):
            if obj.name in self._multi_shapes_objs:
                return self._multi_shapes_objs[obj.name]
            return self.get_normal_object(obj.name)
        elif isinstance(obj, PhysxArticulationLinkComponent):
            articulated_model = self.get_articulation(obj.articulation.name)
            if articulated_model is None:
                return None

            # TODO: this is too complex
            fcl_model = articulated_model.get_fcl_model()
            col_links = fcl_model.get_collision_objects()
            col_link_names = fcl_model.get_collision_link_names()
            for col_link, col_link_name in zip(col_links, col_link_names):
                if col_link_name == obj.name:
                    return col_link
            return None
        else:
            raise TypeError(f"Unknown type: {type(obj)}")

    def check_collision(
        self,
        obj_A: PhysxArticulation | PhysxArticulationLinkComponent | Entity,
        obj_B: PhysxArticulation | PhysxArticulationLinkComponent | Entity,
    ) -> list[WorldCollisionResult]:
        """
        Check collision between two objects,
        which can either be a PhysxArticulation or an Entity.

        Note:
            Currently there's no support for checking between two PhysxArticulation.
            This is planned but not yet implemented.

        :param obj_A: object A to check for collision.
        :param obj_B: object B to check for collision.
        :return: a list of WorldCollisionResult. Empty if there's no collision.
        """
        # Ensure that if there's only one PhysxArticulation, it's always obj_A
        if isinstance(obj_B, PhysxArticulation):
            obj_A, obj_B = obj_B, obj_A

        # TODO: support both obj_A and obj_B being PhysxArticulation
        if isinstance(obj_A, PhysxArticulation) and isinstance(
            obj_B, PhysxArticulation
        ):
            raise NotImplementedError(
                "No support for checking between two PhysxArticulation yet."
            )

        col_objs_A = self._get_col_obj(obj_A)
        col_objs_B = self._get_col_obj(obj_B)

        # Check if obj_A or obj_B does not exist
        if col_objs_A is None or col_objs_B is None:
            return []

        if not isinstance(col_objs_A, list):
            col_objs_A = [col_objs_A]
        if not isinstance(col_objs_B, list):
            col_objs_B = [col_objs_B]

        ret = []
        for col_obj_A in col_objs_A:
            for col_obj_B in col_objs_B:
                result = collide(col_obj_A, col_obj_B)

                if isinstance(result, list):
                    ret.extend(result)
                elif result.is_collision():
                    world_result = WorldCollisionResult()
                    world_result.res = result
                    world_result.collision_type = "sceneobject_sceneobject"
                    world_result.object_name1 = obj_A.name
                    world_result.object_name2 = obj_B.name
                    world_result.link_name1 = obj_A.name
                    world_result.link_name2 = obj_B.name
                    ret.append(world_result)
        return ret

    def distance_to_collision(
        self,
        obj_A: PhysxArticulation | PhysxArticulationLinkComponent | Entity,
        obj_B: PhysxArticulation | PhysxArticulationLinkComponent | Entity,
    ) -> WorldDistanceResult:
        """
        Compute the distance to the nearest collision between two objects
        (ignoring self-collisions for PhysxArticulation).
        The objects can either be a PhysxArticulation or an Entity.

        Note:
            Currently there's no support for checking between two PhysxArticulation.
            This is planned but not yet implemented.

        :param obj_A: object A to compute distance to nearest collision.
        :param obj_B: object B to compute distance to nearest collision.
        :return: an instance of WorldDistanceResult
        """
        # Ensure that if there's only one PhysxArticulation, it's always obj_A
        if isinstance(obj_B, PhysxArticulation):
            obj_A, obj_B = obj_B, obj_A

        # TODO: support both obj_A and obj_B being PhysxArticulation
        if isinstance(obj_A, PhysxArticulation) and isinstance(
            obj_B, PhysxArticulation
        ):
            raise NotImplementedError(
                "No support for checking between two PhysxArticulation yet."
            )

        col_objs_A = self._get_col_obj(obj_A)
        col_objs_B = self._get_col_obj(obj_B)

        # Check if obj_A or obj_B does not exist
        if col_objs_A is None or col_objs_B is None:
            return WorldDistanceResult()

        if not isinstance(col_objs_A, list):
            col_objs_A = [col_objs_A]
        if not isinstance(col_objs_B, list):
            col_objs_B = [col_objs_B]

        ret = WorldDistanceResult()
        for col_obj_A in col_objs_A:
            for col_obj_B in col_objs_B:
                result = distance(col_obj_A, col_obj_B)

                if result.min_distance < ret.min_distance:
                    if isinstance(result, WorldDistanceResult):
                        ret = result
                    else:
                        ret.res = result
                        ret.min_distance = min(ret.min_distance, result.min_distance)
                        ret.distance_type = "sceneobject_sceneobject"
                        ret.object_name1 = obj_A.name
                        ret.object_name2 = obj_B.name
                        ret.link_name1 = obj_A.name
                        ret.link_name2 = obj_B.name
        return ret

    @staticmethod
    def convert_sapien_col_shape(
        component: PhysxRigidBaseComponent,
    ) -> list[CollisionObject]:
        """Converts a SAPIEN physx.PhysxRigidBaseComponent to an FCL CollisionObject
        Returns a list of collision_obj at their current poses.

        If the component is an articulation link, the returned collision_obj is at
        the shape's local_pose.
        Otherwise, the returned collision_obj is at the entity's global pose
        """
        shapes = component.collision_shapes
        if len(shapes) == 0:
            return []

        # NOTE: MPlib currently only supports 1 collision shape per object
        # TODO: multiple collision shapes
        # assert len(shapes) == 1, (
        #     f"Should only have 1 collision shape, got {len(shapes)} shapes for "
        #     f"entity '{component.entity.name}'"
        # )
        if len(shapes) > 1:
            print(f"Got {len(shapes)} shapes for entity '{component.entity.name}'")
            print(
                "\x1b[33;1m"
                "[Warning] only 1 collision shape per component is properly supported.\n"
                "          Currently, a hack is used to temporarily bypass this issue.\n"
                "          Some PlanningWorld features (e.g., attached body)\n"
                "          might not function correctly."
                "\x1b[0m"
            )

        col_shapes = []
        for shape in shapes:
            if isinstance(
                component, PhysxArticulationLinkComponent
            ):  # articulation link
                pose = shape.local_pose
            else:
                pose = component.entity.pose * shape.local_pose

            if isinstance(shape, PhysxCollisionShapeBox):
                collision_geom = Box(side=shape.half_size * 2)
            elif isinstance(shape, PhysxCollisionShapeCapsule):
                collision_geom = Capsule(radius=shape.radius, lz=shape.half_length * 2)
                # NOTE: physx Capsule has x-axis along capsule height
                # FCL Capsule has z-axis along capsule height
                pose = pose * Pose(q=euler2quat(0, np.pi / 2, 0))
            elif isinstance(shape, PhysxCollisionShapeConvexMesh):
                assert np.allclose(
                    shape.scale, 1.0
                ), f"Not unit scale {shape.scale}, need to rescale vertices?"
                collision_geom = Convex(vertices=shape.vertices, faces=shape.triangles)
            elif isinstance(shape, PhysxCollisionShapeCylinder):
                collision_geom = Cylinder(radius=shape.radius, lz=shape.half_length * 2)
                # NOTE: physx Cylinder has x-axis along cylinder height
                # FCL Cylinder has z-axis along cylinder height
                pose = pose * Pose(q=euler2quat(0, np.pi / 2, 0))
            elif isinstance(shape, PhysxCollisionShapePlane):
                # # PhysxCollisionShapePlane are actually a halfspace
                # # https://nvidia-omniverse.github.io/PhysX/physx/5.3.1/docs/Geometry.html#planes
                # n = pose.to_transformation_matrix()[:3, 0]  # PxPlane normal is +x
                # d = n.dot(pose.p)  # type: ignore
                # collision_geom = Halfspace(n=n, d=d)

                # TODO: investigate wrong fcl::Halfspace collision checks
                # and distance query seg fault
                print(
                    "\x1b[33;1m"
                    "[Warning] No support for PhysxCollisionShapePlane yet."
                    "\x1b[0m"
                )
                continue
            elif isinstance(shape, PhysxCollisionShapeSphere):
                collision_geom = Sphere(radius=shape.radius)
            elif isinstance(shape, PhysxCollisionShapeTriangleMesh):
                collision_geom = BVHModel()
                collision_geom.beginModel()
                collision_geom.addSubModel(shape.get_vertices(), shape.get_triangles())
                collision_geom.endModel()
            else:
                raise TypeError(f"Unknown shape type: {type(shape)}")
            col_shapes.append(CollisionObject(collision_geom, pose.p, pose.q))
        return col_shapes


class SapienPlanner(Planner):
    def __init__(
        self,
        sapien_planning_world: SapienPlanningWorld,
        move_group: str,
        joint_vel_limits: Union[Sequence[float], np.ndarray] = None,
        joint_acc_limits: Union[Sequence[float], np.ndarray] = None,
    ):
        r"""wrapper around sapien planner.

        Args:
            planning_world: SapienPlanningWorld which inherits from mplib.planning_world.PlanningWorld
            move_group: name of the move group (end effector link)
            joint_vel_limits: joint velocity limits (supplement)
            joint_acc_limits: joint acceleration limits (supplement)

        """
        # first get user link names and joint names, assuming one robot
        sapien_articulation: PhysxArticulation = (
            sapien_planning_world._sim_scene.get_all_articulations()[0]
        )
        self.user_link_names = [link.name for link in sapien_articulation.links]
        self.user_joint_names = [
            joint.name for joint in sapien_articulation.active_joints
        ]

        self.urdf = export_kinematic_chain_urdf(sapien_articulation)
        self.srdf = export_srdf(sapien_articulation)
        if self.srdf == "" and os.path.exists(self.urdf.replace(".urdf", ".srdf")):
            self.srdf = self.urdf.replace(".urdf", ".srdf")
            print("No SRDF file provided. Try to load %s." % self.srdf)

        self.joint_name_2_idx = {}
        for i, joint in enumerate(self.user_joint_names):
            self.joint_name_2_idx[joint] = i
        self.link_name_2_idx = {}
        for i, link in enumerate(self.user_link_names):
            self.link_name_2_idx[link] = i

        # only support one robot with hard coded name "robot"
        self.robot = sapien_planning_world.get_articulation("robot")
        self.pinocchio_model = self.robot.get_pinocchio_model()

        self.planning_world = sapien_planning_world
        self.acm = self.planning_world.get_allowed_collision_matrix()

        if self.srdf == "":
            self.generate_collision_pair()
            self.robot.update_SRDF(self.srdf)

        assert move_group in self.user_link_names
        self.move_group = move_group
        self.robot.set_move_group(self.move_group)
        self.move_group_joint_indices = self.robot.get_move_group_joint_indices()

        self.joint_types = self.pinocchio_model.get_joint_types()
        self.joint_limits = np.concatenate(self.pinocchio_model.get_joint_limits())
        self.planner = OMPLPlanner(world=self.planning_world)
        if joint_vel_limits is None:
            joint_vel_limits = np.ones(len(self.move_group_joint_indices))
        if joint_acc_limits is None:
            joint_acc_limits = np.ones(len(self.move_group_joint_indices))
        self.joint_vel_limits = joint_vel_limits
        self.joint_acc_limits = joint_acc_limits
        self.move_group_link_id = self.link_name_2_idx[self.move_group]
        assert len(self.joint_vel_limits) == len(self.move_group_joint_indices), len(
            self.move_group_joint_indices
        )
        assert len(self.joint_acc_limits) == len(self.move_group_joint_indices)

        # Mask for joints that have equivalent values (revolute joints with range > 2pi)
        self.equiv_joint_mask = [
            t.startswith("JointModelR") for t in self.joint_types
        ] & (self.joint_limits[:, 1] - self.joint_limits[:, 0] > 2 * np.pi)
