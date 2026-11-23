/* Один клиент, один незавершённый запрос, не более MAX_RETRIES повторов.
   Каждый d_step — один переход абстрактной модели. */

#ifndef MAX_RETRIES
#define MAX_RETRIES 2
#endif

mtype = { Idle, Waiting, Done };
mtype phase = Idle;
bool issued = false;
bool pending = false;
bool ack = false;
bool expired = false;
byte retries = 0;

inline show_state() {
    printf("STATE phase=%e issued=%d pending=%d ack=%d expired=%d retries=%d\n",
           phase, issued, pending, ack, expired, retries)
}

active proctype Protocol() {
    do
    :: d_step {
        phase == Idle ->
        issued = true;
        pending = true;
        ack = false;
        expired = false;
        retries = 0;
        phase = Waiting;
        show_state()
    }
    :: d_step {
        phase == Waiting ->
        pending = false;
        ack = true;
#ifdef DOUBLE_OUTCOME
        expired = true;
#endif
        phase = Done;
        show_state()
    }
    :: d_step {
#ifdef RETRY_OVERFLOW
        phase == Waiting && retries <= MAX_RETRIES ->
#else
        phase == Waiting && retries < MAX_RETRIES ->
#endif
        retries++;
        show_state()
    }
    :: d_step {
        phase == Waiting && retries >= MAX_RETRIES ->
        pending = false;
        expired = true;
        phase = Done;
        show_state()
    }
    :: d_step {
        phase == Done ->
#ifdef NO_RESET
        skip;
#else
        phase = Idle;
        issued = false;
        ack = false;
        expired = false;
        retries = 0;
#endif
        show_state()
    }
#ifdef SPURIOUS_OUTCOME
    :: d_step {
        phase == Idle ->
        ack = true;
        phase = Done;
        show_state()
    }
#endif
#ifdef STALLED
    :: d_step {
        phase == Waiting && retries == MAX_RETRIES ->
        skip;
        show_state()
    }
#endif
    od
}

/* Безопасность — запрещённое состояние не возникает. */
ltl exclusive     { [] !(ack && expired) }
ltl requested     { [] ((ack || expired) -> issued) }
ltl retry_bound   { [] (retries <= MAX_RETRIES) }
ltl pending_clean { [] (pending -> (issued && !ack && !expired)) }

/* Живость — ожидание завершается, после завершения отправляется новый запрос. */
ltl response      { [] (pending -> <> (ack || expired)) }
ltl next_request  { [] ((phase == Done) -> <> pending) }
