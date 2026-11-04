-- Prints 20,000 report notes, then fails an assertion.
-- Used to check that the failure message survives output truncation.
entity chatty_fail_tb is
end entity;

architecture sim of chatty_fail_tb is
begin
  process
  begin
    for i in 1 to 20000 loop
      report "step " & integer'image(i) severity note;
    end loop;
    assert false report "FINAL CHECK FAILED" severity failure;
    wait;
  end process;
end architecture;
