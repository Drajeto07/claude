import re
from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict


class ApiModel(BaseModel):
    """Base of everything the API sends or receives. In the OpenAPI schema, a
    response field with a default counts as required, since it is always sent;
    the frontend's generated types (frontend/types/generated/api.ts) then don't
    mark it optional. Changes the schema only, never validation or output."""

    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


# What XML 1.0 can't hold, so no Word file can (SEC-023): the C0 control codes but tab,
# newline and carriage return; unpaired surrogates; U+FFFE and U+FFFF. A PDF's broken
# font or pasted text can carry them, and python-docx refuses to write any.
NOT_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f\ud800-\udfff\ufffe\uffff]")
# The ones that separate words (vertical tab, form feed, the four separators) become a
# space, so the words on either side stay two.
_SPACES = str.maketrans(dict.fromkeys("\x0b\x0c\x1c\x1d\x1e\x1f", " "))


def xml_text(value: str) -> str:
    """`value` without what XML can't hold."""
    if NOT_XML.search(value) is None:
        return value
    return NOT_XML.sub("", value.translate(_SPACES))


# A document's text: whoever sends it -- an importer, the editor, the AI -- it holds only
# what a Word file can.
XmlText = Annotated[str, AfterValidator(xml_text)]
