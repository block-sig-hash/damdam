"""Imports every model module, so `SQLModel.metadata` is complete.

A foreign key can only be resolved once the table it targets is registered, and
registration happens as a side effect of importing the module that declares it.
That makes `SQLModel.metadata.create_all` quietly dependent on which modules a
caller happened to import — a test touching payments fails on `quotes`, fixing
that makes it fail on `sales_markets`, and so on down a chain nobody chose.

`app/main.py` avoids the problem by importing everything anyway. Tests do not,
so they import this instead:

    from app import model_registry  # noqa: F401
    SQLModel.metadata.create_all(engine)

One line, one reason, and no chain to chase.
"""

# ruff: noqa: F401

from app.activation import service as _activation
from app.audit import models as _audit
from app.auth import models as _auth
from app.catalog import market as _catalog_market
from app.catalog import models as _catalog
from app.catalog import quotes as _catalog_quotes
from app.catalog import tariffs as _catalog_tariffs
from app.checkins import models as _checkins
from app.connectivity import models as _connectivity
from app.controls import models as _controls
from app.esim import models as _esim
from app.fulfilment import models as _fulfilment
from app.identity import models as _identity
from app.ledger import models as _ledger
from app.mfa import models as _mfa
from app.orders import models as _orders
from app.organizations import models as _organizations
from app.packages import models as _packages
from app.payments import contract as _payments_contract
from app.profile import models as _profile
from app.refunds import models as _refunds
from app.sos import models as _sos
from app.usage import models as _usage
from app.voice import models as _voice
