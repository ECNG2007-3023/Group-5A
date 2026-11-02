library ieee;
use ieee.std_logic_1164.all;

entity runaway_tb is
end entity;

architecture sim of runaway_tb is
  signal clk : std_logic := '0';
begin
  -- Clock that never stops: the simulation runs forever without a time limit.
  clk <= not clk after 1 ns;
end architecture;
