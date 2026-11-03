library ieee;
use ieee.std_logic_1164.all;

entity valid_test_tb is
end entity;

architecture test of valid_test_tb is
    signal a : std_logic := '0';
    signal y : std_logic;
begin
    uut: entity work.valid_test
        port map (a => a, y => y);

    process
    begin
        a <= '0';
        wait for 10 ns;
        assert y = '0' report "Output mismatch" severity failure;

        a <= '1';
        wait for 10 ns;
        assert y = '1' report "Output mismatch" severity failure;

        wait;
    end process;
end architecture;
