library ieee;
use ieee.std_logic_1164.all;

entity invalid_syntax is
    port (
        a : in std_logic;
        y : out std_logic
    );
end entity;

architecture behavioral of invalid_syntax is
begin
    y <= a
end architecture;
