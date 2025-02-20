# Copyright 2022 Pants project contributors (see CONTRIBUTORS.md).
# Licensed under the Apache License, Version 2.0 (see LICENSE).

from __future__ import annotations

from itertools import product
from textwrap import dedent

import pytest

from pants.backend.helm.target_types import HelmChartTarget
from pants.backend.helm.testutil import (
    HELM_CHART_FILE,
    HELM_TEMPLATE_HELPERS_FILE,
    HELM_VALUES_FILE,
    K8S_SERVICE_FILE,
)
from pants.backend.helm.util_rules import sources
from pants.backend.helm.util_rules.sources import HelmChartSourceFiles, HelmChartSourceFilesRequest
from pants.build_graph.address import Address
from pants.core.target_types import FilesGeneratorTarget, ResourcesGeneratorTarget
from pants.core.util_rules import stripped_source_files
from pants.engine.rules import QueryRule
from pants.testutil.rule_runner import RuleRunner


@pytest.fixture
def rule_runner() -> RuleRunner:
    return RuleRunner(
        target_types=[HelmChartTarget, ResourcesGeneratorTarget, FilesGeneratorTarget],
        rules=[
            *sources.rules(),
            *stripped_source_files.rules(),
            QueryRule(HelmChartSourceFiles, (HelmChartSourceFilesRequest,)),
        ],
    )


def test_source_templates_are_always_included(rule_runner: RuleRunner) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                helm_chart(name='mychart', dependencies=[':resources', ':files'])
                resources(name="resources", sources=['*.xml'])
                files(name="files", sources=['*.txt'])
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
            "resource.xml": "",
            "file.txt": "",
        }
    )

    address = Address("", target_name="mychart")
    tgt = rule_runner.get_target(address)
    source_files = rule_runner.request(
        HelmChartSourceFiles,
        [
            HelmChartSourceFilesRequest.create(
                tgt, include_metadata=False, include_resources=False, include_files=False
            )
        ],
    )

    assert source_files.snapshot.files == (
        "templates/_helpers.tpl",
        "templates/service.yaml",
        "values.yaml",
    )


_TEST_INCLUDE_SOURCES_PARAMETERS = [tuple(params) for params in product((True, False), repeat=3)]


@pytest.mark.parametrize(
    "include_metadata, include_resources, include_files", _TEST_INCLUDE_SOURCES_PARAMETERS
)
def test_source_templates_includes(
    rule_runner: RuleRunner, include_metadata: bool, include_resources: bool, include_files: bool
) -> None:
    rule_runner.write_files(
        {
            "BUILD": dedent(
                """\
                helm_chart(name='mychart', dependencies=[':resources', ':files'])
                resources(name="resources", sources=['*.xml'])
                files(name="files", sources=['*.txt'])
                """
            ),
            "Chart.yaml": HELM_CHART_FILE,
            "values.yaml": HELM_VALUES_FILE,
            "templates/_helpers.tpl": HELM_TEMPLATE_HELPERS_FILE,
            "templates/service.yaml": K8S_SERVICE_FILE,
            "resource.xml": "",
            "file.txt": "",
        }
    )

    address = Address("", target_name="mychart")
    tgt = rule_runner.get_target(address)
    source_files = rule_runner.request(
        HelmChartSourceFiles,
        [
            HelmChartSourceFilesRequest.create(
                tgt,
                include_metadata=include_metadata,
                include_resources=include_resources,
                include_files=include_files,
            )
        ],
    )

    if include_metadata:
        assert "Chart.yaml" in source_files.snapshot.files
    if include_resources:
        assert "resource.xml" in source_files.snapshot.files
    if include_files:
        assert "file.txt" in source_files.snapshot.files
