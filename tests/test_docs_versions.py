"""Consistency checks between the docs and docker-compose.yml.

The compose file is the single source of truth for which image
version the stack runs. The two Markdown documents repeat that
version in prose and in runnable snippets, where nothing would
otherwise notice them going stale after a bump. These tests grep the
prose so the copies cannot drift in silence.

The cost is a constraint on how a version may be written: only a full
`<repository>:<tag>` reference is recognised, so a bare `v3.13.2`
falls outside the check.
"""

import re

import pytest
import yaml

DOCS = ("CLAUDE.md", "README.md")
TAG_CHARACTERS = r"([\w.\-]+)"


@pytest.fixture(scope="session")
def compose_images(repo_root):
    """Map each pinned repository to the tag compose pins it to."""
    compose = yaml.safe_load((repo_root / "docker-compose.yml").read_text())
    images = [
        service["image"]
        for service in compose["services"].values()
        if "image" in service
    ]
    assert images
    return dict(image.rsplit(":", 1) for image in images)


def find_references(text, repository):
    """Return every tag the text gives that repository."""
    pattern = re.compile(re.escape(repository) + ":" + TAG_CHARACTERS)
    return pattern.findall(text)


def test_documented_image_tags_match_compose(repo_root, compose_images):
    """Confirm no document names a tag the compose file does not."""
    for name in DOCS:
        text = (repo_root / name).read_text()
        for repository, tag in compose_images.items():
            for found in find_references(text, repository):
                assert found == tag, f"{name}: {repository}:{found}"


def test_the_documents_reference_the_pinned_images(repo_root, compose_images):
    """Confirm the check above is not passing on an empty scan.

    A renamed repository would make every grep miss, leaving the
    drift check vacuously green. This fails instead.
    """
    for repository in compose_images:
        found = [
            name
            for name in DOCS
            if find_references((repo_root / name).read_text(), repository)
        ]
        assert found, repository
