"""Preflight validation for Notion data source IDs and schemas."""

from __future__ import annotations

from dataclasses import dataclass, field
import logging

import requests

from ..schema import EntryFields, SubscriptionFields
from ..utils.config import Config
from .client import NotionClient

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class PropertySpec:
    name: str
    type: str


@dataclass
class DataSourceValidationResult:
    role: str
    data_source_id: str
    data_source: dict | None = None
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class SchemaValidationError(RuntimeError):
    """Raised when Notion setup validation finds blocking problems."""


ARTICLE_REQUIRED_PROPERTIES = [
    PropertySpec(EntryFields.NAME, "title"),
    PropertySpec(EntryFields.URL, "url"),
    PropertySpec(EntryFields.PUBLISHED, "date"),
    PropertySpec(EntryFields.STATE, "select"),
    PropertySpec(EntryFields.SOURCE, "relation"),
]

ARTICLE_OPTIONAL_TYPED_PROPERTIES = [
    PropertySpec(EntryFields.PARENT_ITEM, "relation"),
]

FEED_REQUIRED_PROPERTIES = [
    PropertySpec(SubscriptionFields.NAME, "title"),
    PropertySpec(SubscriptionFields.URL, "url"),
    PropertySpec(SubscriptionFields.STATUS, "select"),
]

FEED_OPTIONAL_TYPED_PROPERTIES = [
    PropertySpec(SubscriptionFields.FILTERLIST, "multi_select"),
    PropertySpec(SubscriptionFields.CLEANUP_DAYS, "number"),
    PropertySpec(SubscriptionFields.FETCH_AMOUNT, "number"),
]

FEED_OPTIONAL_WARNING_PROPERTIES = [
    PropertySpec(SubscriptionFields.LAST_UPDATE, "last_edited_time"),
    PropertySpec(SubscriptionFields.ARTICLES, "relation"),
]


def validate_notion_setup(client: NotionClient, config: Config) -> None:
    """Validate both configured Notion data sources before sync starts."""
    article_result = validate_data_source(
        client,
        role="Articles",
        data_source_id=config.articles_datasource_id,
        required_properties=ARTICLE_REQUIRED_PROPERTIES,
        optional_typed_properties=ARTICLE_OPTIONAL_TYPED_PROPERTIES,
        env_name="NOTION_ARTICLES_DATABASE_ID",
    )
    feed_result = validate_data_source(
        client,
        role="Feeds",
        data_source_id=config.subscriptions_datasource_id,
        required_properties=FEED_REQUIRED_PROPERTIES,
        optional_typed_properties=FEED_OPTIONAL_TYPED_PROPERTIES,
        optional_warning_properties=FEED_OPTIONAL_WARNING_PROPERTIES,
        env_name="NOTION_FEEDS_DATABASE_ID",
    )

    results = [article_result, feed_result]
    _add_swapped_id_hint(article_result, feed_result)
    _add_source_relation_hint(article_result, feed_result, config.subscriptions_datasource_id)

    for result in results:
        for warning in result.warnings:
            log.warning(warning)

    errors = [error for result in results for error in result.errors]
    if errors:
        raise SchemaValidationError(_format_validation_errors(errors))

    log.info("Notion data source sanity check passed")


def validate_data_source(
    client: NotionClient,
    role: str,
    data_source_id: str,
    required_properties: list[PropertySpec],
    optional_typed_properties: list[PropertySpec] | None = None,
    optional_warning_properties: list[PropertySpec] | None = None,
    env_name: str | None = None,
) -> DataSourceValidationResult:
    """Validate one Notion data source ID and its visible property schema."""
    optional_typed_properties = optional_typed_properties or []
    optional_warning_properties = optional_warning_properties or []
    label = _label(role, env_name)
    result = DataSourceValidationResult(role=role, data_source_id=data_source_id)

    try:
        data_source = client.retrieve_data_source(data_source_id)
    except requests.HTTPError as exc:
        result.errors.append(_format_http_error(label, data_source_id, exc))
        return result
    except Exception as exc:
        result.errors.append(
            f"{label}: unable to retrieve data source `{data_source_id}`: {exc}"
        )
        return result

    result.data_source = data_source
    properties = data_source.get("properties", {})
    if not isinstance(properties, dict):
        result.errors.append(f"{label}: retrieve response did not include a properties schema.")
        return result

    for spec in required_properties:
        _validate_property(label, properties, spec, result.errors)

    for spec in optional_typed_properties:
        if spec.name in properties:
            _validate_property(label, properties, spec, result.errors)

    for spec in optional_warning_properties:
        if spec.name not in properties:
            result.warnings.append(
                f"{label}: optional property `{spec.name}` is missing; sync can continue."
            )
        else:
            actual_type = properties[spec.name].get("type")
            if actual_type != spec.type:
                result.warnings.append(
                    f"{label}: optional property `{spec.name}` expected `{spec.type}`, got `{actual_type}`."
                )

    if result.errors:
        visible = ", ".join(f"`{name}`" for name in sorted(properties)) or "(none)"
        result.errors.append(f"{label}: visible properties are: {visible}.")

    return result


def _validate_property(
    label: str,
    properties: dict,
    spec: PropertySpec,
    errors: list[str],
) -> None:
    prop = properties.get(spec.name)
    if prop is None:
        errors.append(
            f"{label}: missing property `{spec.name}` (expected type `{spec.type}`). "
            "If you renamed it in Notion, update `rss2notion/schema.py` or rename it back."
        )
        return

    actual_type = prop.get("type")
    if actual_type != spec.type:
        errors.append(
            f"{label}: property `{spec.name}` expected `{spec.type}`, got `{actual_type}`."
        )


def _add_swapped_id_hint(
    article_result: DataSourceValidationResult,
    feed_result: DataSourceValidationResult,
) -> None:
    if article_result.ok and feed_result.ok:
        return

    article_props = _property_names(article_result)
    feed_props = _property_names(feed_result)
    article_looks_like_feed = _has_all(article_props, FEED_REQUIRED_PROPERTIES)
    feed_looks_like_article = _has_all(feed_props, ARTICLE_REQUIRED_PROPERTIES)

    if article_looks_like_feed and feed_looks_like_article:
        hint = (
            "Articles/Feeds IDs may be swapped: "
            "`NOTION_ARTICLES_DATABASE_ID` looks like the subscription data source, "
            "and `NOTION_FEEDS_DATABASE_ID` looks like the articles data source."
        )
        article_result.errors.append(hint)
    elif article_looks_like_feed:
        article_result.errors.append(
            "`NOTION_ARTICLES_DATABASE_ID` may point to the Feeds data source."
        )
    elif feed_looks_like_article:
        feed_result.errors.append(
            "`NOTION_FEEDS_DATABASE_ID` may point to the Articles data source."
        )


def _add_source_relation_hint(
    article_result: DataSourceValidationResult,
    feed_result: DataSourceValidationResult,
    feeds_data_source_id: str,
) -> None:
    if not article_result.data_source:
        return

    source_prop = article_result.data_source.get("properties", {}).get(EntryFields.SOURCE)
    if not source_prop or source_prop.get("type") != "relation":
        return

    relation = source_prop.get("relation", {})
    targets = {
        value
        for key in ("data_source_id", "database_id")
        if (value := relation.get(key))
    }
    expected_targets = {feeds_data_source_id}
    if feed_result.data_source:
        parent = feed_result.data_source.get("parent", {})
        if isinstance(parent, dict):
            expected_targets.update(
                value
                for key in ("database_id", "data_source_id")
                if (value := parent.get(key))
            )

    if targets and targets.isdisjoint(expected_targets):
        article_result.errors.append(
            f"Articles: property `{EntryFields.SOURCE}` is a relation, but it does not appear "
            "to target the configured Feeds data source. Check the relation target in Notion."
        )
    elif not targets:
        article_result.warnings.append(
            f"Articles: property `{EntryFields.SOURCE}` is a relation. If sync later fails, "
            "check that it targets the configured Feeds data source."
        )


def _format_http_error(label: str, data_source_id: str, exc: requests.HTTPError) -> str:
    response = exc.response
    status_code = response.status_code if response is not None else None
    message = _notion_error_message(response)

    if status_code == 401:
        return (
            f"{label}: Notion token was rejected while retrieving `{data_source_id}`. "
            "Check `NOTION_API_KEY`."
            f"{_message_suffix(message)}"
        )
    if status_code == 403:
        return (
            f"{label}: integration cannot access `{data_source_id}`. "
            "Share both original Notion databases with the integration and confirm it has read/write content capabilities."
            f"{_message_suffix(message)}"
        )
    if status_code == 404:
        return (
            f"{label}: data source `{data_source_id}` was not found or is not visible to this integration. "
            "Check the ID, use Copy data source ID from Manage data sources, and avoid linked databases/data sources."
            f"{_message_suffix(message)}"
        )
    return (
        f"{label}: Notion API returned HTTP {status_code} while retrieving `{data_source_id}`."
        f"{_message_suffix(message)}"
    )


def _notion_error_message(response: requests.Response | None) -> str:
    if response is None:
        return ""
    try:
        body = response.json()
    except ValueError:
        return response.text.strip()
    return str(body.get("message", "")).strip()


def _message_suffix(message: str) -> str:
    return f" Notion message: {message}" if message else ""


def _format_validation_errors(errors: list[str]) -> str:
    return "Notion setup validation failed:\n" + "\n".join(f"- {error}" for error in errors)


def _property_names(result: DataSourceValidationResult) -> set[str]:
    if not result.data_source:
        return set()
    properties = result.data_source.get("properties", {})
    return set(properties) if isinstance(properties, dict) else set()


def _has_all(properties: set[str], specs: list[PropertySpec]) -> bool:
    return all(spec.name in properties for spec in specs)


def _label(role: str, env_name: str | None) -> str:
    return f"{role} ({env_name})" if env_name else role
