library ieee;
use ieee.std_logic_1164.all;

entity and_gate_tb is
end entity;

architecture sim of and_gate_tb is
  signal a, b, y : std_logic;
begin
  dut : entity work.and_gate port map (a => a, b => b, y => y);
  process
  begin
    a <= '0'; b <= '0'; wait for 10 ns; assert y = '0' report "0 and 0 failed" severity error;
    a <= '0'; b <= '1'; wait for 10 ns; assert y = '0' report "0 and 1 failed" severity error;
    a <= '1'; b <= '0'; wait for 10 ns; assert y = '0' report "1 and 0 failed" severity error;
    a <= '1'; b <= '1'; wait for 10 ns; assert y = '1' report "1 and 1 failed" severity error;
    wait;
  end process;
end architecture;
