/* P09, упражнение 6. Удалён переход s1 -> s1. */
mtype = { s0, s1, s2, s3 };
mtype state = s0;

active proctype RequestResponse() {
    do
    :: d_step { state == s0 -> state = s1; printf("STATE state=%e\n", state) }
    :: d_step { state == s1 -> state = s2; printf("STATE state=%e\n", state) }
    :: d_step { state == s2 -> state = s0; printf("STATE state=%e\n", state) }
    :: d_step { state == s3 -> state = s3; printf("STATE state=%e\n", state) }
    od
}

ltl safety      { [] (state != s3) }
ltl response    { [] ((state == s1) -> <> (state == s2)) }
ltl return_idle { [] ((state == s2) -> <> (state == s0)) }
