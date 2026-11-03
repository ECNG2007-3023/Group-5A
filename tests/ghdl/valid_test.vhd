library ieee;
use ieee.std_logic_1164.all;

entity valid_test is
    port (
        a : in std_logic;
        y : out std_logic
    );
end entity;

architecture behavioral of valid_test is
begin
    y <= a;
end architecture;
