"""P03 capacity unit handling (kW -> MW) — the ledger-27 phantom-fleet fix.

ksj:generatingPower is kW per the KSJ P03 spec; the parser previously
took it as MW (36,200 kW solar -> 36,200 "MW") and let the -1 unknown
sentinel through as a value. Pins: conversion, sentinel rejection, and
plausibility bounds.
"""

from scripts.enrich_plants_p03 import parse_p03

_GML = """<?xml version="1.0" encoding="UTF-8"?>
<ksj:Dataset xmlns:ksj="http://nlftp.mlit.go.jp/ksj/schemas/ksj-app"
             xmlns:gml="http://www.opengis.net/gml/3.2"
             xmlns:xlink="http://www.w3.org/1999/xlink" gml:id="ds">
  <gml:Point gml:id="p1"><gml:pos>36.40 139.28</gml:pos></gml:Point>
  <gml:Point gml:id="p2"><gml:pos>35.50 140.00</gml:pos></gml:Point>
  <gml:Point gml:id="p3"><gml:pos>35.60 139.50</gml:pos></gml:Point>
  <ksj:ThermalPowerPlant gml:id="t1">
    <ksj:position xlink:href="#p1"/>
    <ksj:nameOfPlant>みどり市メガソーラー</ksj:nameOfPlant>
    <ksj:nameOfOwner>テスト電力</ksj:nameOfOwner>
    <ksj:address>群馬県</ksj:address>
    <ksj:generatingPower>36200</ksj:generatingPower>
    <ksj:burningType>LNG</ksj:burningType>
  </ksj:ThermalPowerPlant>
  <ksj:ThermalPowerPlant gml:id="t2">
    <ksj:position xlink:href="#p2"/>
    <ksj:nameOfPlant>不明出力発電所</ksj:nameOfPlant>
    <ksj:nameOfOwner>X</ksj:nameOfOwner>
    <ksj:address>千葉県</ksj:address>
    <ksj:generatingPower>-1</ksj:generatingPower>
    <ksj:burningType>LNG</ksj:burningType>
  </ksj:ThermalPowerPlant>
  <ksj:ThermalPowerPlant gml:id="t3">
    <ksj:position xlink:href="#p3"/>
    <ksj:nameOfPlant>過大値発電所</ksj:nameOfPlant>
    <ksj:nameOfOwner>Y</ksj:nameOfOwner>
    <ksj:address>東京都</ksj:address>
    <ksj:generatingPower>99999999</ksj:generatingPower>
    <ksj:burningType>LNG</ksj:burningType>
  </ksj:ThermalPowerPlant>
</ksj:Dataset>
"""


def test_generating_power_kw_to_mw_and_bounds(tmp_path):
    gml = tmp_path / "p03.xml"
    gml.write_text(_GML, encoding="utf-8")
    plants = {p["name"]: p for p in parse_p03(str(gml))}
    assert plants["みどり市メガソーラー"]["capacity_mw"] == 36.2   # kW -> MW
    assert plants["不明出力発電所"]["capacity_mw"] is None          # sentinel
    assert plants["過大値発電所"]["capacity_mw"] is None            # > 9,000 MW
