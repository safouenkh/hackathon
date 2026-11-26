from decimal import Decimal

from scripts.mariadb_dump import parse_dump, pg_type

DUMP = r"""
CREATE TABLE `lots` (
  `LOT_ID` int(11) NOT NULL,
  `ZONE_ID` varchar(50) NOT NULL,
  `LOT_SUP_LOTIS` int(11) DEFAULT 0,
  `PRIX` decimal(10,3) DEFAULT NULL,
  `NOTE` text NOT NULL,
  `CONTRAT_DATE` date DEFAULT NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

INSERT INTO `lots` (`LOT_ID`, `ZONE_ID`, `LOT_SUP_LOTIS`, `PRIX`, `NOTE`, `CONTRAT_DATE`) VALUES
(1, '930301', -120, 12.345, 'l\'usine ; (a),(b)', NULL),
(2, '932107X', 0, NULL, 'ligne1\nligne2 et '' quote', '2020-01-31');
INSERT INTO `lots` (`LOT_ID`, `ZONE_ID`, `LOT_SUP_LOTIS`, `PRIX`, `NOTE`, `CONTRAT_DATE`) VALUES
(3, '1', 5, 0.500, 'antislash \\ fin', '');

ALTER TABLE `lots`
  ADD PRIMARY KEY (`LOT_ID`),
  ADD UNIQUE KEY `ZONE_ID` (`ZONE_ID`,`LOT_SUP_LOTIS`),
  ADD KEY `idx_note` (`NOTE`);
ALTER TABLE `lots`
  MODIFY `LOT_ID` int(11) NOT NULL AUTO_INCREMENT, AUTO_INCREMENT=7205;
"""


def test_columns_and_types():
    tables = parse_dump(DUMP)
    cols = tables["lots"].columns
    assert [c.name for c in cols] == ["LOT_ID", "ZONE_ID", "LOT_SUP_LOTIS", "PRIX", "NOTE", "CONTRAT_DATE"]
    assert [c.nullable for c in cols] == [False, False, True, True, False, True]
    assert [pg_type(c.mysql_type) for c in cols] == [
        "integer", "varchar(50)", "integer", "numeric(10,3)", "text", "date",
    ]


def test_rows_values_and_escapes():
    rows = parse_dump(DUMP)["lots"].rows
    assert len(rows) == 3
    assert rows[0] == [1, "930301", -120, Decimal("12.345"), "l'usine ; (a),(b)", None]
    assert rows[1] == [2, "932107X", 0, None, "ligne1\nligne2 et ' quote", "2020-01-31"]
    assert rows[2][3] == Decimal("0.500")
    assert rows[2][4] == "antislash \\ fin"


def test_keys():
    t = parse_dump(DUMP)["lots"]
    assert t.primary_key == ["LOT_ID"]
    assert t.unique_keys == [["ZONE_ID", "LOT_SUP_LOTIS"]]
    assert t.indexes == [["NOTE"]]


def test_pg_type_mapping():
    assert pg_type("bigint(20) UNSIGNED") == "bigint"
    assert pg_type("tinyint(1)") == "smallint"
    assert pg_type("tinyint(4)") == "smallint"
    assert pg_type("mediumtext") == "text"
    assert pg_type("longtext") == "text"
    assert pg_type("timestamp") == "timestamp"
    assert pg_type("decimal(7,2)") == "numeric(7,2)"
