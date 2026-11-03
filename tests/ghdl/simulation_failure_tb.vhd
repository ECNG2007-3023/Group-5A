entity simulation_failure_tb is
end entity;

architecture test of simulation_failure_tb is
begin
    process
    begin
        assert false
            report "Intentional simulation failure"
            severity failure;
        wait;
    end process;
end architecture;
