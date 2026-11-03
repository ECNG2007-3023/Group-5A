
library IEEE;
use IEEE.STD_LOGIC_1164.ALL;

entity and_gate_tb is
end and_gate_tb;

architecture Behavioral of and_gate_tb is

    signal A : STD_LOGIC := '0';
    signal B : STD_LOGIC := '0';
    signal Y : STD_LOGIC;

begin

    uut: entity work.and_gate
        port map (
            A => A,
            B => B,
            Y => Y
        );

    process
    begin
        A <= '0';
        B <= '0';
        wait for 10 ns;
        assert Y = '0' report "00 failed" severity error;

        A <= '0';
        B <= '1';
        wait for 10 ns;
        assert Y = '0' report "01 failed" severity error;

        A <= '1';
        B <= '0';
        wait for 10 ns;
        assert Y = '0' report "10 failed" severity error;

        A <= '1';
        B <= '1';
        wait for 10 ns;
        assert Y = '1' report "11 failed" severity error;

        report "All AND gate tests passed";
        wait;
    end process;

end Behavioral;
