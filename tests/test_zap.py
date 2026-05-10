from __future__ import annotations

from postlight.scanners.base import Severity
from postlight.scanners.zap import ZapBaselineScanner


_SAMPLE_REPORT = {
    "@version": "2.14.0",
    "site": [
        {
            "@name": "http://example.com",
            "@host": "example.com",
            "alerts": [
                {
                    "pluginid": "10049",
                    "name": "Storable and Cacheable Content",
                    "riskcode": "0",
                    "count": "1",
                    "instances": [{"uri": "http://example.com/info", "method": "GET"}],
                },
                {
                    "pluginid": "10038",
                    "name": "Content Security Policy Header Not Set",
                    "riskcode": "2",
                    "count": "3",
                    "instances": [
                        {"uri": "http://example.com/", "method": "GET"},
                        {"uri": "http://example.com/login", "method": "GET"},
                        {"uri": "http://example.com/admin", "method": "GET"},
                    ],
                    "cweid": "693",
                },
                {
                    "pluginid": "40003",
                    "name": "CRLF Injection",
                    "riskcode": "3",
                    "count": "1",
                    "instances": [{"uri": "http://example.com/redirect", "method": "GET"}],
                    "cweid": "113",
                },
            ],
        }
    ],
}


def test_parse_empty_returns_no_findings():
    scanner = ZapBaselineScanner("http://example.com")
    assert list(scanner._parse({})) == []
    assert list(scanner._parse({"site": []})) == []
    assert list(scanner._parse({"site": [{"alerts": []}]})) == []


def test_parse_maps_each_alert_to_a_finding():
    scanner = ZapBaselineScanner("http://example.com")
    findings = list(scanner._parse(_SAMPLE_REPORT))
    assert len(findings) == 3
    assert all(f.source_tool == "zap-baseline" for f in findings)


def test_parse_severity_mapping():
    scanner = ZapBaselineScanner("http://example.com")
    findings = list(scanner._parse(_SAMPLE_REPORT))
    by_rule = {f.rule_id: f for f in findings}
    assert by_rule["10049"].severity == Severity.INFO       # riskcode 0
    assert by_rule["10038"].severity == Severity.MEDIUM     # riskcode 2
    assert by_rule["40003"].severity == Severity.HIGH       # riskcode 3


def test_parse_message_includes_url_and_count():
    scanner = ZapBaselineScanner("http://example.com")
    findings = list(scanner._parse(_SAMPLE_REPORT))
    csp = next(f for f in findings if f.rule_id == "10038")
    assert "Content Security Policy" in csp.message
    assert "http://example.com/" in csp.message
    assert "3 occurrences" in csp.message


def test_parse_singular_vs_plural_count():
    scanner = ZapBaselineScanner("http://example.com")
    findings = list(scanner._parse(_SAMPLE_REPORT))
    info = next(f for f in findings if f.rule_id == "10049")
    assert "1 occurrence" in info.message
    assert "occurrences" not in info.message


def test_parse_handles_missing_count_field():
    scanner = ZapBaselineScanner("http://example.com")
    data = {
        "site": [
            {
                "@name": "http://example.com",
                "alerts": [
                    {
                        "pluginid": "1",
                        "name": "x",
                        "riskcode": "1",
                        "instances": [{"uri": "http://example.com/a"}, {"uri": "http://example.com/b"}],
                    }
                ],
            }
        ]
    }
    findings = list(scanner._parse(data))
    assert len(findings) == 1
    assert "2 occurrences" in findings[0].message


def test_parse_falls_back_when_alertref_only():
    scanner = ZapBaselineScanner("http://example.com")
    data = {
        "site": [
            {
                "@name": "http://example.com",
                "alerts": [
                    {
                        "alertRef": "10049-1",
                        "name": "x",
                        "riskcode": "0",
                        "count": "1",
                        "instances": [],
                    }
                ],
            }
        ]
    }
    findings = list(scanner._parse(data))
    assert findings[0].rule_id == "10049-1"


def test_zap_findings_have_no_file_for_annotations():
    # ZAP findings shouldn't produce inline code annotations — they're URL-based.
    scanner = ZapBaselineScanner("http://example.com")
    findings = list(scanner._parse(_SAMPLE_REPORT))
    assert all(f.file is None for f in findings)
    assert all(f.line is None for f in findings)
