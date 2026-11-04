-- Never waits, so simulation time never advances and --stop-time cannot
-- end it. Only the service's wall-clock timeout can stop this job.
entity runaway_tb is
end entity;

architecture sim of runaway_tb is
begin
  process
  begin
    loop
    end loop;
  end process;
end architecture;
