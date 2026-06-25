import json
import unittest

import requests

from rss2notion.notion.validation import (
    ARTICLE_REQUIRED_PROPERTIES,
    FEED_OPTIONAL_TYPED_PROPERTIES,
    FEED_REQUIRED_PROPERTIES,
    validate_data_source,
    validate_notion_setup,
    SchemaValidationError,
)
from rss2notion.schema import EntryFields, SubscriptionFields


class FakeClient:
    def __init__(self, responses):
        self.responses = responses

    def retrieve_data_source(self, data_source_id):
        response = self.responses[data_source_id]
        if isinstance(response, Exception):
            raise response
        return response


class FakeConfig:
    entries_datasource_id = "articles-id"
    feeds_datasource_id = "feeds-id"


def data_source(properties):
    return {
        "object": "data_source",
        "id": "fake-id",
        "properties": properties,
    }


def prop(prop_type, **extra):
    value = {"type": prop_type, prop_type: extra}
    if not extra:
        value[prop_type] = {}
    return value


def article_properties():
    return {
        EntryFields.NAME: prop("title"),
        EntryFields.URL: prop("url"),
        EntryFields.PUBLISHED: prop("date"),
        EntryFields.STATE: prop("select"),
        EntryFields.SOURCE: prop("relation", data_source_id="feeds-id"),
    }


def feed_properties():
    return {
        SubscriptionFields.NAME: prop("title"),
        SubscriptionFields.URL: prop("url"),
        SubscriptionFields.STATUS: prop("select"),
        SubscriptionFields.FILTERLIST: prop("multi_select"),
        SubscriptionFields.CLEANUP_DAYS: prop("number"),
        SubscriptionFields.FETCH_AMOUNT: prop("number"),
    }


def http_error(status_code, message):
    response = requests.Response()
    response.status_code = status_code
    response._content = json.dumps({"message": message}).encode()
    error = requests.HTTPError(f"{status_code} error")
    error.response = response
    return error


class ValidateDataSourceTests(unittest.TestCase):
    def test_valid_schema_passes(self):
        result = validate_data_source(
            FakeClient({"articles-id": data_source(article_properties())}),
            "Articles",
            "articles-id",
            ARTICLE_REQUIRED_PROPERTIES,
        )

        self.assertTrue(result.ok)
        self.assertEqual([], result.errors)

    def test_missing_required_property_fails(self):
        properties = article_properties()
        del properties[EntryFields.URL]

        result = validate_data_source(
            FakeClient({"articles-id": data_source(properties)}),
            "Articles",
            "articles-id",
            ARTICLE_REQUIRED_PROPERTIES,
        )

        self.assertFalse(result.ok)
        self.assertIn("missing property `URL`", "\n".join(result.errors))

    def test_wrong_property_type_fails(self):
        properties = article_properties()
        properties[EntryFields.NAME] = prop("rich_text")

        result = validate_data_source(
            FakeClient({"articles-id": data_source(properties)}),
            "Articles",
            "articles-id",
            ARTICLE_REQUIRED_PROPERTIES,
        )

        self.assertFalse(result.ok)
        self.assertIn("expected `title`, got `rich_text`", "\n".join(result.errors))

    def test_optional_missing_does_not_fail(self):
        result = validate_data_source(
            FakeClient({"feeds-id": data_source(feed_properties())}),
            "Feeds",
            "feeds-id",
            FEED_REQUIRED_PROPERTIES,
            optional_typed_properties=FEED_OPTIONAL_TYPED_PROPERTIES,
        )

        self.assertTrue(result.ok)

    def test_swapped_ids_include_hint(self):
        client = FakeClient(
            {
                "articles-id": data_source(feed_properties()),
                "feeds-id": data_source(article_properties()),
            }
        )

        with self.assertRaises(SchemaValidationError) as ctx:
            validate_notion_setup(client, FakeConfig())

        self.assertIn("IDs may be swapped", str(ctx.exception))

    def test_http_error_mapping(self):
        cases = [
            (401, "Check `NOTION_API_KEY`"),
            (403, "integration cannot access"),
            (404, "was not found or is not visible"),
        ]
        for status_code, expected in cases:
            with self.subTest(status_code=status_code):
                result = validate_data_source(
                    FakeClient({"bad-id": http_error(status_code, "notion says no")}),
                    "Articles",
                    "bad-id",
                    ARTICLE_REQUIRED_PROPERTIES,
                )

                self.assertFalse(result.ok)
                self.assertIn(expected, "\n".join(result.errors))


if __name__ == "__main__":
    unittest.main()
