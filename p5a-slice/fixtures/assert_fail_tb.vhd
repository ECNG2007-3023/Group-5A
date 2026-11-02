library ieee;
use ieee.std_logic_1164.all;

entity assert_fail_tb is
end entity;

architecture sim of assert_fail_tb is
  signal a, b, y : std_logic;
begin
  dut : entity work.and_gate port map (a => a, b => b, y => y);
  process
  begin
    a <= '1'; b <= '1'; wait for 10 ns;
    assert y = '0' report "deliberate failure: expected 0" severity failure;
    wait;
  end process;
end architecture;
