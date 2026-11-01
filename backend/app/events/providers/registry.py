"""Pick real services or fakes from the settings (ADR 0003)."""

from dataclasses import dataclass

import anthropic

from app.events.config import EventsSettings
from app.events.providers import fakes
from app.events.providers.anthropic_llm import AnthropicLlm
from app.events.providers.apify import ApifyPostSearch
from app.events.providers.apollo import ApolloEnrichment
from app.events.providers.protocols import EmailVerifier, Llm, PeopleEnrichment, PostSearch, WebFetcher
from app.events.providers.reoon import ReoonVerifier
from app.events.providers.webfetch import SafeFetcher


class ProviderConfigError(ValueError):
    """Real providers were asked for, but a key they need isn't set."""


@dataclass(frozen=True)
class Providers:
    fetcher: WebFetcher
    llm: Llm
    search: PostSearch
    enrichment: PeopleEnrichment
    verifier: EmailVerifier | None  # None: the optional second email check is off


def build_providers(settings: EventsSettings) -> Providers:
    if settings.providers == "fake":
        return Providers(
            fetcher=fakes.FakeFetcher(),
            llm=fakes.FakeLlm(),
            search=fakes.FakePostSearch(),
            enrichment=fakes.FakeEnrichment(),
            verifier=fakes.FakeEmailVerifier() if settings.reoon_enabled else None,
        )

    missing = settings.missing()
    if missing:
        raise ProviderConfigError("The events tool needs " + ", ".join(missing))

    def secret(value: object) -> str:
        return value.get_secret_value()  # type: ignore[attr-defined, no-any-return]

    llm: Llm = AnthropicLlm(
        # No retries inside the SDK: an attempt that timed out may have been billed, and its cost has to reach the
        # budget (ADR 0002). The job queue retries instead, accounting for each attempt.
        client=anthropic.Anthropic(api_key=secret(settings.anthropic_api_key), max_retries=0),
        analyze_model=settings.analyze_model,
        classify_model=settings.classify_model,
        analyze_effort=settings.analyze_effort,
        classify_effort=settings.classify_effort,
        max_web_searches=settings.max_web_searches,
        fallbacks=settings.llm_fallbacks,
    )
    return Providers(
        fetcher=SafeFetcher(),
        llm=llm,
        search=ApifyPostSearch(
            secret(settings.apify_token), actor=settings.apify_actor, posted_limit=settings.apify_posted_limit
        ),
        enrichment=ApolloEnrichment(secret(settings.apollo_api_key)),
        verifier=ReoonVerifier(secret(settings.reoon_api_key)) if settings.reoon_enabled else None,
    )
