#!/usr/bin/env python3

import sys, os, re, datetime, time
from threading import Thread
from deltabot_cli import BotCli
from deltachat2 import EventType, MsgData, events

cli = BotCli("elissa")

class WaitJob(Thread):
    def __init__(self, bot, accid: int, chatid: int, timestamp: int):
        super().__init__(); self.daemon = True
        taskfile = f"{bot.user_basedir}/tasks/a{accid}c{chatid}.wait"
        with open(taskfile, "w") as f:
            print(timestamp, file=f)
        bot.logger.info(
            f"Scheduled task a{accid}c{chatid}.wait for " +
            datetime.datetime.fromtimestamp(timestamp)\
                             .strftime("%m/%d/%y %H:%M:%S")
        )
        self.bot = bot; self.a = accid; self.c = chatid; self.t = timestamp
    def run(self):
        bot = self.bot; accid = self.a; chatid = self.c; timestamp = self.t
        now = int(datetime.datetime.now().strftime('%s'))
        time.sleep(max(0, timestamp - now))
        userdir, script, pointer = get_userdir(bot, accid, chatid)
        if pointer < len(script) and script[pointer]["reply"].strip():
            reply = MsgData(text=script[pointer]["reply"])
            log_message(userdir, reply)
            bot.rpc.send_msg(accid, chatid, reply)
        advance_instruction_pointer(userdir)
        os.remove(f"{bot.user_basedir}/tasks/a{accid}c{chatid}.wait")
        bot.logger.info(f"Task a{accid}c{chatid}.wait finished successfully")
        continue_execution(bot, accid, chatid, userdir, script)

@cli.on_start
def on_start(bot, args):
    if not args.script: exit("The --script option is mandatory with serve")
    with open(args.script) as f:
        bot.script = f.read()
        bot.user_basedir = args.config_dir
    try:
        _ = parse_script(bot.script)
    except Exception as e:
        exit(e)
    bot.logger.info(f"Script file '{args.script}' read without errors")
    # Wake any tasks that might have been left from a previous run
    taskdir = f"{bot.user_basedir}/tasks"
    if not os.path.isdir(taskdir): os.makedirs(taskdir)
    for t in os.listdir(taskdir):
        if not t.endswith(".wait"): continue
        a, c = map(int, re.match(r"a([0-9]+)c([0-9]+)\.wait", t)\
                          .groups())
        with open(f"{taskdir}/{t}") as f:
            timestamp = int(f.read())
        bot.logger.info(f"Resurrecting task {t}")
        WaitJob(bot, a, c, timestamp).start()

@cli.on(events.RawEvent)
def log_event(bot, accid, event):
    if event.kind == EventType.SECUREJOIN_INVITER_PROGRESS \
    and event.progress == 1000 \
    and not bot.rpc.get_contact(accid, event.contact_id).is_bot:
        # Bot's QR scanned by an user. This could be a new chat.
        chatid = bot.rpc.create_chat_by_contact_id(accid, event.contact_id)
        bot.logger.info(f"Created chat 'a{accid}c{chatid}'")
        userdir, script, pointer = get_userdir(bot, accid, chatid)
        # If applicable, send greeting message
        if pointer == 0 and len(script) > 0 and script[0]["command"] == "":
            reply = MsgData(text=script[0]["reply"])
            log_message(userdir, reply)
            bot.rpc.send_msg(accid, chatid, reply)
            advance_instruction_pointer(userdir)
        # Start executing the script until it blocks.
        continue_execution(bot, accid, event.msg.chat_id, userdir, script)

def get_userdir(bot, accid: int, chatid: int) -> tuple[str,list[dict],int]:
    """
    Read the userdir (or initialize it if it does not yet exist).

    Returns: userdir, script, instruction_pointer
    """
    userdir = f"{bot.user_basedir}/chats/a{accid}c{chatid}"
    if not os.path.isdir(userdir):
        os.makedirs(userdir)
        with open(f"{userdir}/script", "w") as f:
            f.write(bot.script)
        with open(f"{userdir}/instruction_pointer", "w") as f:
            print(0, file=f)
    with open(f"{userdir}/script") as f:
        script = parse_script(f.read())
    with open(f"{userdir}/instruction_pointer") as f:
        pointer = int(f.read())
    return userdir, script, pointer

@cli.on(events.NewMessage)
def handle_message(bot, accid, event):
    userdir, script, pointer = get_userdir(bot, accid, event.msg.chat_id)
    log_message(userdir, event.msg)
    if pointer >= len(script):
        bot.logger.info(f"No instructions left in script for {userdir}")
        return
    inst = script[pointer]
    if inst["command"] == "wait-for":
        if event.msg.view_type.lower() != inst["args"][0] \
                    or ("match" in inst and \
                    event.msg.text.split() != inst["match"]):
            if "otherwise" in inst and inst["otherwise"]:
                reply = MsgData(text=" ".join(inst["otherwise"]))
                bot.rpc.send_msg(accid, event.msg.chat_id, reply)
                log_message(userdir, reply)
            return
    elif inst["command"] == "wait":
        # We are currently executing a wait command. Therefore, we ignore
        # all incoming messages at this stage, possibly executing an
        # "otherwise" action in the process. After the wait command is
        # done, the execution pointer will be advanced independently of
        # incoming messages (see below).
        if "otherwise" in inst and inst["otherwise"]:
            reply = MsgData(text=" ".join(inst["otherwise"]))
            bot.rpc.send_msg(accid, event.msg.chat_id, reply)
            log_message(userdir, reply)
        return
    else:
        # If we encounter an unknown command at this point, we log an
        # error and proceed as if the command was successful. Note that
        # this code path should be dead since the script is validated
        # when it is read.
        c = inst["command"]
        bot.logger.error(f"Processed reply for unknown command '{c}' in"\
                         f"'{userdir}/script' at instruction {pointer}.")
    # Since we did not return early, the instruction seems to have worked.
    if inst["reply"].strip():
        reply = MsgData(text=inst["reply"])
        bot.rpc.send_msg(accid, event.msg.chat_id, reply)
        log_message(userdir, reply)
    advance_instruction_pointer(userdir)
    continue_execution(bot, accid, event.msg.chat_id, userdir, script)

def advance_instruction_pointer(userdir) -> None:
    with open(f"{userdir}/instruction_pointer") as f:
        pointer = int(f.read())
    with open(f"{userdir}/instruction_pointer", "w") as f:
        print(pointer+1, file=f)
def continue_execution(bot, accid, chatid, userdir, script) -> None:
    with open(f"{userdir}/instruction_pointer") as f:
        pointer = int(f.read())
    if pointer >= len(script):
        # TODO: This was the last instruction. If any action is to be
        # taken after the last instruction, take that action here!
        return
    elif script[pointer]["command"] == "wait-for":
        return                          # Block until the next message arrives
    elif script[pointer]["command"] == "wait":
        amount, unit = script[pointer]["args"]
        if unit == "sec":
            delta = int(amount)
        elif unit == "min":
            delta = int(amount) * 60
        elif unit == "h":
            delta = int(amount) * 60 * 60
        elif unit == "d":
            delta = int(amount) * 60 * 60 * 24
        else:
            bot.logger.error(f"Unknown unit of time '{unit}' found in "\
                             f"{userdir}/script at instruction {pointer}.")
            delta = 0   # The best we can do at this point
        t = int(datetime.datetime.now().strftime('%s')) + delta
        WaitJob(bot, accid, chatid, t).start()
        return                          # Block until the wait job terminates
    else:
        # If we encounter an unknown command at this point, we log an
        # error and simply ignore the command.
        c = inst["command"]
        bot.logger.error(f"Skipped unknown command '{c}' in"\
                         f"'{userdir}/script' at instruction {pointer}.")
    advance_instruction_pointer(userdir)
    continue_execution(bot, accid, chatid, userdir, script)

def log_message(userdir: str, message) -> None:
    with open(f"{userdir}/conversation.log", "a") as f:
        print(message, file=f)

def parse_command(command: str) -> dict:
    result = {}
    if not command.startswith('%'):
        raise Exception('Commands must start with "%"')
    context = "start"
    for word in command[1:].strip().split():
        if context == "start":
            result["command"] = word
            context = "args"
            result[context] = []
        elif word == "%match%":
            context = "match"
            result[context] = []
        elif word == "%otherwise%":
            context = "otherwise"
            result[context] = []
        else:
            result[context].append(word)
    return result

def validate_script(parsed_script: list[dict]) -> None:
    # Validate the script semantics; otherwise raise an exception
    for i, inst in enumerate(parsed_script):
        # Check that "command" and "reply" exist.
        if not "command" in inst:
            raise Exception(f"Instruction {i} has no command")
        if not "reply" in inst:
            raise Exception(f"Instruction {i} has no reply")
        # Check that command is within a known set of commands and has
        # the expected arguments.
        if inst["command"] == "":
            pass    # This is allowed and results in the greeting message.
        elif inst["command"] == "wait-for":
            if len(inst["args"]) != 1:
                raise Exception(f"Error at instruction {i}: "\
                                 "wait-for takes exactly one argument")
            if inst["args"][0] not in ["text", "voice", "image"]:
                raise Exception(f"Error at instruction {i}: "\
                                 "the type must be text, voice or image")
            if "match" in inst and inst["args"][0] != "text":
                raise Exception(f"Error at instruction {i}: "\
                                 "%match% is only allowed with wait-for text")
        elif inst["command"] == "wait":
            if len(inst["args"]) != 2:
                raise Exception(f"Error at instruction {i}: "\
                                 "wait takes exactly two arguments")
            elif inst["args"][1] not in ["sec", "min", "h", "d"]:
                raise Exception(f"Error at instruction {i}: "\
                                 "the type unit be sec, min, h or d")
            try:
                _ = int(inst["args"][0])
            except Exception:
                arg0 = inst["args"][0]
                raise Exception(f"Error at instruction {i}: "\
                                f"unable to parse '{arg0}' as an integer")
        else:
            c = inst["command"]
            raise Exception(f"Unknown command '{c}' found at instruction {i}")

def parse_script(script: str):
    result = []; textblock = ""; command = None
    for line in script.splitlines():
        if line.lstrip().startswith('%'):
            if command or textblock:
                if not command: command = {"command": ""}
                result.append({
                    **command, "reply": textblock.strip(),
                })
            textblock = ""; command = parse_command(line.lstrip())
        else:
            textblock += line
    if command or textblock:
        result.append({
            **command, "reply": textblock.strip(),
        })
    validate_script(result)
    return result

if __name__ == "__main__":
    cli.add_generic_option("--script",
                           help="Filename of the elissa script to use")
    try:
        cli.start()
    except KeyboardInterrupt:
        pass
