from pydantic import BaseModel, ValidationError


class MarketDataError(RuntimeError):
    pass


def _validate(schema: type[BaseModel], row: dict) -> None:
    try:
        schema.model_validate(row)
    except ValidationError as exc:
        # Report fields and error types, never private row values.
        fields = ", ".join(
            f"{'.'.join(str(p) for p in item['loc'])}:{item['type']}"
            for item in exc.errors(include_input=False)
        )
        raise MarketDataError(f"Invalid {schema.__name__} row: {fields}") from None
