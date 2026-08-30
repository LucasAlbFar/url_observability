"""Consistency checks between the docs and the pinned images.

The compose file and the Dockerfiles are the single source of truth
for which image version the stack runs. The two Markdown documents
repeat that version in prose and in runnable snippets, where nothing
would otherwise notice them going stale after a bump. These tests
grep the prose so the copies cannot drift in silence.

Reading `image:` alone would leave every locally built service out:
`app`, `service-go` and `service-node` declare `build:`, so their
base tags were quoted in prose and checked by nothing. The
`pinned_images` fixture reads both.

The cost is a constraint on how a version may be written: only a full
`<repository>:<tag>` reference is recognised, so a bare `v3.13.2`
falls outside the check.
"""

import re

DOCS = ("CLAUDE.md", "README.md")
TAG_CHARACTERS = r"([\w.\-]+)"
# Nothing that could be part of a longer name may sit to the left. The
# fixture holds bare repositories now — `node`, `python`, `golang`,
# `alpine` — so without this, writing `service-node:8004` in prose reads
# as a `node` image on tag `8004` and fails a check about an image
# nobody touched.
LEFT_BOUNDARY = r"(?<![\w./-])"


def find_references(text, repository):
    """Return every tag the text gives that repository."""
    pattern = re.compile(LEFT_BOUNDARY + re.escape(repository) + ":" + TAG_CHARACTERS)
    return pattern.findall(text)


def test_the_stack_pins_one_tag_per_repository(pinned_images):
    """Confirm two files do not pin the same repository differently.

    `Dockerfile` and `worker/Dockerfile` both build on `python`. Two
    patch versions there is drift between images that are meant to be
    the same, and it would also make the check below ambiguous about
    which tag a document should be quoting.
    """
    for repository, tags in pinned_images.items():
        assert len(tags) == 1, f"{repository}: {sorted(tags)}"


def test_documented_image_tags_match_compose(repo_root, pinned_images):
    """Confirm no document names a tag the stack does not pin."""
    for name in DOCS:
        text = (repo_root / name).read_text()
        for repository, tags in pinned_images.items():
            for found in find_references(text, repository):
                assert found in tags, f"{name}: {repository}:{found}"


def test_the_documents_reference_the_pinned_images(repo_root, pinned_images):
    """Confirm the check above is not passing on an empty scan.

    A renamed repository would make every grep miss, leaving the
    drift check vacuously green. This fails instead.
    """
    for repository in pinned_images:
        found = [
            name
            for name in DOCS
            if find_references((repo_root / name).read_text(), repository)
        ]
        assert found, repository
