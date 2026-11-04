-- Allocates and fills 4 MB blocks forever. Must hit the 256 MB memory
-- limit and come back as error "memory_limit".
entity mem_hog_tb is
end entity;

architecture sim of mem_hog_tb is
  type int_array is array (natural range <>) of integer;
  type int_array_ptr is access int_array;
begin
  process
    variable p : int_array_ptr;
  begin

    loop
      p := new int_array(0 to 1_000_000);
      for i in p'range loop
        p(i) := i;
      end loop;
    end loop;
  end process;
end architecture;
