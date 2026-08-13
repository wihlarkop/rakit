from typing import Any, cast

import pytest
from rakit_core.definitions import ResourceFieldPolicy
from rakit_core.errors import RakitError
from rakit_core.relationships import (
    RelationshipCardinality,
    RelationshipDefinition,
    RelationshipEditMode,
    RelationshipKind,
)
from rakit_sqlalchemy.datasource import SQLAlchemyDataSource
from rakit_sqlalchemy.relationships import inspect_relationships, validate_relationship_definition
from sqlalchemy import Column, ForeignKey, String, Table
from sqlalchemy.orm import DeclarativeBase, DynamicMapped, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


order_tag = Table(
    "relationship_order_tag",
    Base.metadata,
    Column("order_id", ForeignKey("relationship_orders.id"), primary_key=True),
    Column("tag_id", ForeignKey("relationship_tags.id"), primary_key=True),
)


class Customer(Base):
    __tablename__ = "relationship_customers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    orders: Mapped[list["Order"]] = relationship(back_populates="customer")


class Tag(Base):
    __tablename__ = "relationship_tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]


class Order(Base):
    __tablename__ = "relationship_orders"

    id: Mapped[int] = mapped_column(primary_key=True)
    customer_id: Mapped[int | None] = mapped_column(ForeignKey("relationship_customers.id"))
    customer: Mapped[Customer | None] = relationship(back_populates="orders")
    readonly_customer: Mapped[Customer | None] = relationship(
        "Customer",
        primaryjoin="Order.customer_id == Customer.id",
        viewonly=True,
    )
    items: Mapped[list["Item"]] = relationship(back_populates="order", cascade="all, delete-orphan")
    tags: Mapped[list[Tag]] = relationship(secondary=order_tag)


class Item(Base):
    __tablename__ = "relationship_items"

    id: Mapped[int] = mapped_column(primary_key=True)
    order_id: Mapped[int] = mapped_column(ForeignKey("relationship_orders.id"))
    sku: Mapped[str]
    order: Mapped[Order] = relationship(back_populates="items")


class Node(Base):
    __tablename__ = "relationship_nodes"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(ForeignKey("relationship_nodes.id"))
    parent: Mapped["Node | None"] = relationship(remote_side="Node.id", back_populates="children")
    children: Mapped[list["Node"]] = relationship(back_populates="parent")


class Student(Base):
    __tablename__ = "relationship_students"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str]
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="student")


class Course(Base):
    __tablename__ = "relationship_courses"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str]
    enrollments: Mapped[list["Enrollment"]] = relationship(back_populates="course")


class Enrollment(Base):
    __tablename__ = "relationship_enrollments"

    id: Mapped[int] = mapped_column(primary_key=True)
    student_id: Mapped[int] = mapped_column(ForeignKey("relationship_students.id"))
    course_id: Mapped[int] = mapped_column(ForeignKey("relationship_courses.id"))
    grade: Mapped[str] = mapped_column(String(2))
    created_at: Mapped[str] = mapped_column(server_default="CURRENT_TIMESTAMP")
    student: Mapped[Student] = relationship(back_populates="enrollments")
    course: Mapped[Course] = relationship(back_populates="enrollments")


class DynamicParent(Base):
    __tablename__ = "relationship_dynamic_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    children: DynamicMapped["DynamicChild"] = relationship(lazy="dynamic")


class DynamicChild(Base):
    __tablename__ = "relationship_dynamic_children"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(ForeignKey("relationship_dynamic_parents.id"))


class ProfileParent(Base):
    __tablename__ = "relationship_profile_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped["Profile | None"] = relationship(back_populates="parent", uselist=False)


class Profile(Base):
    __tablename__ = "relationship_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int | None] = mapped_column(
        ForeignKey("relationship_profile_parents.id"), unique=True
    )
    parent: Mapped[ProfileParent | None] = relationship(back_populates="profile")


class RequiredProfileParent(Base):
    __tablename__ = "relationship_required_profile_parents"

    id: Mapped[int] = mapped_column(primary_key=True)
    profile: Mapped["RequiredProfile | None"] = relationship(back_populates="parent", uselist=False)


class RequiredProfile(Base):
    __tablename__ = "relationship_required_profiles"

    id: Mapped[int] = mapped_column(primary_key=True)
    parent_id: Mapped[int] = mapped_column(
        ForeignKey("relationship_required_profile_parents.id"), unique=True
    )
    parent: Mapped[RequiredProfileParent] = relationship(back_populates="profile")


def test_mapper_relationships_are_classified_without_sqlalchemy_leakage() -> None:
    relationships = inspect_relationships(Order)

    assert relationships["customer"].kind is RelationshipKind.MANY_TO_ONE
    assert relationships["customer"].cardinality is RelationshipCardinality.TO_ONE
    assert relationships["customer"].nullable is True
    assert relationships["items"].kind is RelationshipKind.ONE_TO_MANY
    assert relationships["items"].delete_orphan is True
    assert relationships["tags"].kind is RelationshipKind.MANY_TO_MANY
    assert relationships["tags"].has_secondary is True
    assert inspect_relationships(Node)["parent"].self_referential is True


def test_unique_scalar_relationships_are_one_to_one_in_both_directions() -> None:
    parent_profile = inspect_relationships(ProfileParent)["profile"]
    profile_parent = inspect_relationships(Profile)["parent"]

    assert parent_profile.kind is RelationshipKind.ONE_TO_ONE
    assert profile_parent.kind is RelationshipKind.ONE_TO_ONE
    assert parent_profile.nullable is True
    assert profile_parent.nullable is True


def test_reverse_one_to_one_does_not_inherit_the_child_fk_requiredness() -> None:
    parent_profile = inspect_relationships(RequiredProfileParent)["profile"]
    profile_parent = inspect_relationships(RequiredProfile)["parent"]

    assert profile_parent.kind is RelationshipKind.ONE_TO_ONE
    assert profile_parent.nullable is False
    assert parent_profile.kind is RelationshipKind.ONE_TO_ONE
    assert parent_profile.nullable is True


def test_simple_association_object_requires_declared_scalar_fields_and_target() -> None:
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="enrollments",
        association_target_resource_id="courses",
        label="Courses",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        association_fields=("grade",),
    )

    validate_relationship_definition(
        definition,
        source_model=Student,
        target_model=Enrollment,
        association_target_model=Course,
    )
    metadata = inspect_relationships(Student)["enrollments"]
    assert metadata.association_object_eligible is True
    assert metadata.association_scalar_fields == ("grade",)


def test_association_object_identity_and_foreign_keys_are_not_editable_scalars() -> None:
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="enrollments",
        association_target_resource_id="courses",
        label="Courses",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        association_fields=("id",),
    )
    with pytest.raises(RakitError) as caught:
        validate_relationship_definition(
            definition,
            source_model=Student,
            target_model=Enrollment,
            association_target_model=Course,
        )
    assert caught.value.details["reason"] == "association_fields_not_declared_by_mapper"

    foreign_key = definition.model_copy(update={"association_fields": ("student_id",)})
    with pytest.raises(RakitError) as caught:
        validate_relationship_definition(
            foreign_key,
            source_model=Student,
            target_model=Enrollment,
            association_target_model=Course,
        )
    assert caught.value.details["reason"] == "association_fields_not_declared_by_mapper"


def test_association_object_rejects_undeclared_mapper_scalar_field() -> None:
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="enrollments",
        association_target_resource_id="courses",
        label="Courses",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
        association_fields=("not_a_column",),
    )

    with pytest.raises(RakitError) as caught:
        validate_relationship_definition(
            definition,
            source_model=Student,
            target_model=Enrollment,
            association_target_model=Course,
        )
    assert caught.value.details["reason"] == "association_fields_not_declared_by_mapper"


def test_association_object_rejects_target_mismatch() -> None:
    definition = RelationshipDefinition(
        relationship_id="enrollments",
        target_resource_id="enrollments",
        association_target_resource_id="courses",
        label="Courses",
        kind=RelationshipKind.ASSOCIATION_OBJECT,
        cardinality=RelationshipCardinality.TO_MANY,
    )

    with pytest.raises(RakitError) as caught:
        validate_relationship_definition(
            definition,
            source_model=Student,
            target_model=Enrollment,
            association_target_model=Tag,
        )
    assert caught.value.details["reason"] == "association_target_resource_mismatch"


def test_writable_viewonly_and_dynamic_relationships_fail_closed() -> None:
    readonly = RelationshipDefinition(
        relationship_id="readonly_customer",
        target_resource_id="customers",
        label="Customer",
        kind=RelationshipKind.MANY_TO_ONE,
        cardinality=RelationshipCardinality.TO_ONE,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    with pytest.raises(RakitError) as readonly_error:
        validate_relationship_definition(
            readonly,
            source_model=Order,
            target_model=Customer,
        )
    assert readonly_error.value.details["reason"] == "viewonly_relationship_not_writable"

    dynamic = RelationshipDefinition(
        relationship_id="children",
        target_resource_id="dynamic_children",
        label="Children",
        kind=RelationshipKind.ONE_TO_MANY,
        cardinality=RelationshipCardinality.TO_MANY,
        edit_mode=RelationshipEditMode.LINK,
        writable=True,
    )
    with pytest.raises(RakitError) as dynamic_error:
        validate_relationship_definition(
            dynamic,
            source_model=DynamicParent,
            target_model=DynamicChild,
        )
    assert dynamic_error.value.details["reason"] == "loader_strategy_not_writable"


def test_sqlalchemy_datasource_exposes_only_backend_neutral_relationship_metadata() -> None:
    source = SQLAlchemyDataSource(
        model=Order,
        session_factory=cast(Any, object()),
        field_policy=ResourceFieldPolicy(list_fields=("id",), detail_fields=("id",)),
    )

    metadata = source.relationship_metadata["customer"]

    assert metadata.__class__.__module__ == "rakit_core.relationships"
    assert not hasattr(metadata, "mapper")
