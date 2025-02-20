# Copyright 2021 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from pants.backend.codegen.thrift.apache.python import subsystem
from pants.backend.codegen.thrift.apache.python.subsystem import ThriftPythonSubsystem
from pants.backend.codegen.thrift.apache.rules import (
    GeneratedThriftSources,
    GenerateThriftSourcesRequest,
)
from pants.backend.codegen.thrift.target_types import ThriftDependenciesField, ThriftSourceField
from pants.backend.codegen.utils import find_python_runtime_library_or_raise_error
from pants.backend.python.dependency_inference.module_mapper import ThirdPartyPythonModuleMapping
from pants.backend.python.subsystems.setup import PythonSetup
from pants.backend.python.target_types import PythonResolveField, PythonSourceField
from pants.engine.addresses import Address
from pants.engine.fs import AddPrefix, Digest, Snapshot
from pants.engine.rules import Get, collect_rules, rule
from pants.engine.target import (
    GeneratedSources,
    GenerateSourcesRequest,
    InjectDependenciesRequest,
    InjectedDependencies,
    WrappedTarget,
)
from pants.engine.unions import UnionRule
from pants.source.source_root import SourceRoot, SourceRootRequest
from pants.util.logging import LogLevel


class GeneratePythonFromThriftRequest(GenerateSourcesRequest):
    input = ThriftSourceField
    output = PythonSourceField


@rule(desc="Generate Python from Thrift", level=LogLevel.DEBUG)
async def generate_python_from_thrift(
    request: GeneratePythonFromThriftRequest,
    thrift_python: ThriftPythonSubsystem,
) -> GeneratedSources:
    result = await Get(
        GeneratedThriftSources,
        GenerateThriftSourcesRequest(
            thrift_source_field=request.protocol_target[ThriftSourceField],
            lang_id="py",
            lang_options=thrift_python.gen_options,
            lang_name="Python",
        ),
    )

    # We must add back the source root for Python imports to work properly. Note that the file
    # paths will be different depending on whether `namespace py` was used. See the tests for
    # examples.
    source_root = await Get(
        SourceRoot, SourceRootRequest, SourceRootRequest.for_target(request.protocol_target)
    )
    source_root_restored = (
        await Get(Snapshot, AddPrefix(result.snapshot.digest, source_root.path))
        if source_root.path != "."
        else await Get(Snapshot, Digest, result.snapshot.digest)
    )
    return GeneratedSources(source_root_restored)


class InjectApacheThriftPythonDependencies(InjectDependenciesRequest):
    inject_for = ThriftDependenciesField


@rule
async def find_apache_thrift_python_requirement(
    request: InjectApacheThriftPythonDependencies,
    thrift_python: ThriftPythonSubsystem,
    python_setup: PythonSetup,
    # TODO(#12946): Make this a lazy Get once possible.
    module_mapping: ThirdPartyPythonModuleMapping,
) -> InjectedDependencies:
    if not thrift_python.infer_runtime_dependency:
        return InjectedDependencies()

    wrapped_tgt = await Get(WrappedTarget, Address, request.dependencies_field.address)
    resolve = wrapped_tgt.target.get(PythonResolveField).normalized_value(python_setup)

    addr = find_python_runtime_library_or_raise_error(
        module_mapping,
        request.dependencies_field.address,
        "thrift",
        resolve=resolve,
        resolves_enabled=python_setup.enable_resolves,
        recommended_requirement_name="thrift",
        recommended_requirement_url="https://pypi.org/project/thrift/",
        disable_inference_option=f"[{thrift_python.options_scope}].infer_runtime_dependency",
    )
    return InjectedDependencies([addr])


def rules():
    return (
        *collect_rules(),
        *subsystem.rules(),
        UnionRule(GenerateSourcesRequest, GeneratePythonFromThriftRequest),
        UnionRule(InjectDependenciesRequest, InjectApacheThriftPythonDependencies),
    )
