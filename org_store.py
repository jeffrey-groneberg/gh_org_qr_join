"""Persistence for organizations.

``OrgStore`` is the abstraction the application depends on; ``CosmosOrgStore`` is
the production implementation backed by Azure Cosmos DB for NoSQL. The app is
wired with a concrete store from the composition root, so application code never
needs to know which implementation it is using (or whether it is under test).

Authentication is passwordless: ``DefaultAzureCredential`` uses the App Service
managed identity in Azure and the developer's ``az login`` locally. No account
keys are used or stored.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from azure.cosmos import CosmosClient
from azure.cosmos.exceptions import (
    CosmosResourceExistsError,
    CosmosResourceNotFoundError,
)
from azure.identity import DefaultAzureCredential

from models import Org


class OrgExistsError(Exception):
    """Raised when adding an org whose slug already exists."""


@runtime_checkable
class OrgStore(Protocol):
    """The persistence interface the application depends on."""

    def list(self) -> list[Org]: ...

    def get(self, slug: str) -> Org | None: ...

    def add(self, org: Org) -> None:
        """Persist a new org. Raises ``OrgExistsError`` if the slug exists."""

    def set_passcode(self, slug: str, passcode: str) -> Org | None: ...

    def set_installation_info(
        self, slug: str, installed_by: str, installed_at: str
    ) -> Org | None: ...

    def delete(self, slug: str) -> bool: ...


class CosmosOrgStore:
    """Cosmos DB for NoSQL implementation of :class:`OrgStore`.

    The Cosmos client connects on first use (not at construction), so building
    the app does not require network access and startup/health checks don't
    depend on Cosmos being reachable.
    """

    def __init__(
        self,
        endpoint: str,
        database: str,
        container: str,
        credential=None,
    ) -> None:
        self._endpoint = endpoint
        self._database = database
        self._container_name = container
        self._credential = credential
        self._container_client = None

    @property
    def _container(self):
        if self._container_client is None:
            client = CosmosClient(
                self._endpoint, self._credential or DefaultAzureCredential()
            )
            self._container_client = client.get_database_client(
                self._database
            ).get_container_client(self._container_name)
        return self._container_client

    def list(self) -> list[Org]:
        items = self._container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True,
        )
        orgs = [Org.from_item(item) for item in items]
        orgs.sort(key=lambda o: (o.display_name.lower(), o.slug))
        return orgs

    def get(self, slug: str) -> Org | None:
        try:
            item = self._container.read_item(item=slug, partition_key=slug)
        except CosmosResourceNotFoundError:
            return None
        return Org.from_item(item)

    def add(self, org: Org) -> None:
        try:
            self._container.create_item(body=org.to_item())
        except CosmosResourceExistsError as exc:
            raise OrgExistsError(org.slug) from exc

    def set_installation_info(
        self, slug: str, installed_by: str, installed_at: str
    ) -> Org | None:
        try:
            item = self._container.read_item(item=slug, partition_key=slug)
        except CosmosResourceNotFoundError:
            return None
        item["installed_by"] = installed_by
        item["installed_at"] = installed_at
        self._container.replace_item(item=slug, body=item)
        return Org.from_item(item)

    def set_passcode(self, slug: str, passcode: str) -> Org | None:
        try:
            item = self._container.read_item(item=slug, partition_key=slug)
        except CosmosResourceNotFoundError:
            return None
        item["passcode"] = passcode
        self._container.replace_item(item=slug, body=item)
        return Org.from_item(item)

    def delete(self, slug: str) -> bool:
        try:
            self._container.delete_item(item=slug, partition_key=slug)
        except CosmosResourceNotFoundError:
            return False
        return True
