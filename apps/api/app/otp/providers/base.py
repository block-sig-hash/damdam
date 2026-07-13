from dataclasses import dataclass
from typing import Protocol


class OTPProviderError(Exception):
    pass


@dataclass(frozen=True)
class OTPDispatch:
    reference: str
    delivery_reference: str


class OTPProvider(Protocol):
    name: str

    def send(self, phone_number: str) -> OTPDispatch: ...

    def verify(self, phone_number: str, code: str, reference: str) -> bool: ...
