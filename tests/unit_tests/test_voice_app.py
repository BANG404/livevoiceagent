from voice.app import _parse_custom_parameters


def test_parse_custom_parameters_from_twilio_dict() -> None:
    assert _parse_custom_parameters({"call_sid": "CA123", "caller": "+8613800001234"}) == {
        "call_sid": "CA123",
        "caller": "+8613800001234",
    }


def test_parse_custom_parameters_from_parameter_list() -> None:
    assert _parse_custom_parameters([{"name": "call_sid", "value": "CA123"}]) == {
        "call_sid": "CA123"
    }
