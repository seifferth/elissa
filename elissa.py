#!/usr/bin/env python3

import sys, os, re, datetime, time
from threading import Thread
from zipfile import ZipFile
from deltabot_cli import BotCli
from deltachat2 import EventType, MsgData, events

cli = BotCli("elissa")

def export_contact_vcf(bot, accid: int, chatid: int) -> str:
    """
    Export the contact(s) of the specified chat as a vcard file and
    return the filename.
    """
    vcard = bot.rpc.make_vcard(accid,
                               bot.rpc.get_chat_contacts(accid, chatid))
    if not vcard.endswith("\n"): vcard += "\n"
    filename = f"{bot.user_basedir}/chats/a{accid}c{chatid}/contact.vcf"
    with open(filename, "wb") as f:
        f.write(vcard.encode("utf-8"))
    return filename
def export_chat_log_txt(bot, accid: int, chatid: int) -> str:
    """
    Export the specified chat to an IRC-style text log and return the
    filename.
    """
    mids = bot.rpc.get_message_ids(accid, chatid, False, False)
    msgdict = bot.rpc.get_messages(accid, mids)
    chatlog = []
    for i in mids:
        m = msgdict[str(i)]
        t = datetime.datetime.fromtimestamp(m.timestamp)
        if m.text and not m.sender.auth_name:
            chatlog.append(f"[{t}] {m.text}")
        elif m.text:
            chatlog.append(f"[{t}] {m.sender.auth_name}: {m.text}" +
                           (" [edited]" if m.is_edited else ""))
        if m.file and m.file_name:
            chatlog.append(f"[{t}] {m.sender.auth_name} sent {m.file_name}")
    logfilename = f"{bot.user_basedir}/chats/a{accid}c{chatid}/chat_log.txt"
    with open(logfilename, "wb") as f:
        f.write(("\n".join(chatlog)+"\n").encode("utf-8"))
    return logfilename
def _locate_last(view_type: str, bot, accid: int, chatid: int) -> int:
    botaddr = bot.rpc.get_account_info(accid).addr
    mids = bot.rpc.get_message_ids(accid, chatid, False, False)
    msgdict = bot.rpc.get_messages(accid, mids)
    chatlog = []
    for i in mids[::-1]:
        m = msgdict[str(i)]
        if m.sender.address == botaddr: continue   # Ignore sent messages
        if m.view_type.lower() != view_type.lower(): continue
        return i
    return None
def locate_last_text(bot, accid: int, chatid: int) -> str:
    """
    Locate the last text-based message sent by the user and return
    the message id. If the user has not yet sent a text-based message,
    the return value will be None.
    """
    return _locate_last("text", bot, accid, chatid)
def locate_last_image(bot, accid: int, chatid: int) -> str:
    """
    Locate the last image sent by the user and return the corresponding
    message id. If the user has not yet sent an image, the return value
    will be None.
    """
    return _locate_last("image", bot, accid, chatid)
def locate_last_voice(bot, accid: int, chatid: int) -> str:
    """
    Locate the last voice message sent by the user and return the
    corresponding message id. If the user has not yet sent a voice
    message, the return value will be None.
    """
    return _locate_last("voice", bot, accid, chatid)
def export_media_zip(bot, accid: int, chatid: int) -> str:
    """
    Export all media found in the specified chat to a zip file and return
    the filename. If there are no media in the chat, the return value
    will be None.
    """
    mids = bot.rpc.get_message_ids(accid, chatid, False, False)
    msgdict = bot.rpc.get_messages(accid, mids)
    media = {}
    for i in mids:
        m = msgdict[str(i)]
        if m.file and m.file_name:
            media[m.file_name] = m.file
    if not media: return None
    zipfilename = f"{bot.user_basedir}/chats/a{accid}c{chatid}/media.zip"
    with ZipFile(zipfilename, "w") as z:
        for name, path in media.items():
            with open(path, "rb") as f_in:
                with z.open(name, "w") as f_out:
                    f_out.write(f_in.read())
    return zipfilename
def export_full_chat_zip(bot, accid: int, chatid: int) -> str:
    """
    Export the full specified chat to a zip file and return the filename.
    """
    contact_vcf = export_contact_vcf(bot, accid, chatid)
    chat_log_txt = export_chat_log_txt(bot, accid, chatid)
    media_zip = export_media_zip(bot, accid, chatid)
    zipfilename = f"{bot.user_basedir}/chats/a{accid}c{chatid}/full_chat.zip"
    with ZipFile(zipfilename, "w") as z:
        with z.open("contact.vcf", "w") as f_out:
            with open(contact_vcf, "rb") as f_in:
                f_out.write(f_in.read())
        with z.open("chat_log.txt", "w") as f_out:
            with open(chat_log_txt, "rb") as f_in:
                f_out.write(f_in.read())
        with ZipFile(media_zip) as z_in:
            for filename in z_in.namelist():
                with z.open(filename, "w") as f_out:
                    with z_in.open(filename) as f_in:
                        f_out.write(f_in.read())
    return zipfilename

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
        userdir, script, pointer = load_userdir(bot, accid, chatid)
        if pointer < len(script) and script[pointer]["reply"].strip():
            reply = MsgData(text=script[pointer]["reply"])
            log_message(userdir, reply)
            bot.rpc.send_msg(accid, chatid, reply)
        advance_instruction_pointer(userdir)
        os.remove(f"{bot.user_basedir}/tasks/a{accid}c{chatid}.wait")
        bot.logger.info(f"Task a{accid}c{chatid}.wait finished successfully")
        continue_execution(bot, accid, chatid, userdir, script)

@cli.on_init
def on_init(bot, args):
    acclist = bot.rpc.get_all_accounts()
    for acc in acclist:
        if not acc.display_name: continue
        c = bot.rpc.get_basic_chat_info(acc.id,
                                        cli.get_admin_chat(bot.rpc, acc.id))
        newname = f"{acc.display_name} Admins"
        if c.name != newname: bot.rpc.set_chat_name(acc.id, c.id, newname)

@cli.on_start
def on_start(bot, args):
    if not args.script: exit("The --script option is mandatory with serve")
    with open(args.script) as f:
        bot.script = f.read()
        bot.user_basedir = args.config_dir
    try:
        _ = parse_script(bot.script)
        bot.logger.info(f"Script file '{args.script}' read without errors")
    except Exception as e:
        exit(e)
    acclist = bot.rpc.get_all_accounts(); n = len(acclist)
    bot.logger.info(f"This bot is using {n} account{'s' if n!=1 else ''}")
    for acc in acclist:
        admins = bot.rpc.get_chat_contacts(acc.id,
                                    cli.get_admin_chat(bot.rpc, acc.id))
        admin_names = []
        for admin_id in admins:
            a = bot.rpc.get_contact(acc.id, admin_id)
            if acc.addr == a.address and a.name == "Me": continue
            admin_names.append(a.name_and_addr)
        if admin_names:
            bot.logger.info(f"Admin group for account {acc.id}: " +
                            (", ".join(admin_names)))
        else:
            bot.logger.info(f"Admin group for account {acc.id} is empty")
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
        if cli.is_admin(bot.rpc, accid, event.contact_id):
            name = bot.rpc.get_contact(accid, event.contact_id).name_and_addr
            bot.logger.info(f"User {name} joined the admin group"\
                            f" for account {accid}")
            return
        # Bot's QR scanned by an user. This could be a new chat.
        chatid = bot.rpc.create_chat_by_contact_id(accid, event.contact_id)
        bot.logger.info(f"Created chat 'a{accid}c{chatid}'")
        userdir, script, pointer = load_userdir(bot, accid, chatid)
        # If applicable, send greeting message
        if pointer == 0 and len(script) > 0 and script[0]["command"] == "":
            reply = MsgData(text=script[0]["reply"])
            log_message(userdir, reply)
            bot.rpc.send_msg(accid, chatid, reply)
            advance_instruction_pointer(userdir)
        # Start executing the script until it blocks.
        continue_execution(bot, accid, chatid, userdir, script)

def load_userdir(bot, accid: int, chatid: int) -> tuple[str,list[dict],int]:
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

def is_regular_chat(bot, accid, chatid) -> bool:
    chat_type = bot.rpc.get_basic_chat_info(accid, chatid).chat_type
    if chat_type == 100:
        return True         # This is probably an e2ee 1:1 conversation
    elif chat_type == 120:
        return False        # This is probably an e2ee group chat
    else:
        bot.logger.warning(f"Treating unknown chat a{accid}c{chatid} of type"\
                           f" '{chat_type}' as a kind of non-regular chat")
        return False

@cli.on(events.NewMessage)
def handle_message(bot, accid, event):
    if not is_regular_chat(bot, accid, event.msg.chat_id):
        return  # Do not send messages to non 1:1 conversations
    elif cli.is_admin(bot.rpc, accid, event.msg.sender.id):
        return  # Do not treat admins as if they were regular users
    userdir, script, pointer = load_userdir(bot, accid, event.msg.chat_id)
    log_message(userdir, event.msg)
    if pointer >= len(script):
        return  # Ignore messages that arrive after the script is finished
    inst = script[pointer]
    if pointer == 0 and inst["command"] == "":
        # The greeting should have been sent right after secure join;
        # but there might conceivably be some edge cases where this did
        # not work as intended, so in these cases, we send the greeting
        # at this point and log a warning.
        bot.logger.warning("Using greeting to reply to user message in chat"\
                          f" {userdir}")
    elif inst["command"] == "wait-for":
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
        # If we encounter an unknown command at this point, we log a
        # warning and simply ignore the command.
        c = inst["command"]
        bot.logger.warning(f"Ignoring unknown command '{c}' in"\
                           f" '{userdir}/script' at instruction {pointer}."\
                            " This could potentially indicate that the"\
                            " script is now blocked.")
        return
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
    elif script[pointer]["command"] == "notify":
        recipient, *notification = script[pointer]["args"]
        rid = 0
        if recipient == "admins":
            rid = cli.get_admin_chat(bot.rpc, accid)
            if rid == 0:
                bot.logger.error("Unable to notify admins: admin chat "\
                                f"for account {accid} is not configured.")
            elif len(bot.rpc.get_chat_contacts(accid, rid)) < 2:
                bot.logger.warning("Executing 'notify admins' instruction "\
                                  f"for account {accid} with an empty "\
                                   "admin chat.")
        else:
            bot.logger.error("Ignoring notify for unknown recipient "\
                            f"'{recipient}' in {userdir}/script "\
                            f"at instruction {pointer}.")
        if rid != 0:
            notification = " ".join(notification).strip(); attachments = []
            if "attach" in script[pointer]:
                for a in script[pointer]["attach"]:
                    if a == "contact.vcf":     func = export_contact_vcf
                    elif a == "chat_log.txt":  func = export_chat_log_txt
                    elif a == "last-text":     func = locate_last_text
                    elif a == "last-image":    func = locate_last_image
                    elif a == "last-voice":    func = locate_last_voice
                    elif a == "media.zip":     func = export_media_zip
                    elif a == "full_chat.zip": func = export_full_chat_zip
                    else: func = None; bot.logger.error(
                        f"Skipping unknown attachment '{a}' requested in "\
                        f"{userdir}/script at instruction {pointer}.")
                    # If the requested item exists, add it to the list
                    # of attachments
                    filename = func(bot, accid, chatid)
                    if filename != None: attachments.append(filename)
            def send_attachments(attachments: list):
                for a in attachments:
                    if type(a) == str:      # An actual file attachment
                        bot.rpc.send_msg(accid, rid, MsgData(file=a))
                    elif type(a) == int:    # A message to be forwarded
                        bot.rpc.forward_messages(accid, [a], rid)
                    else:
                        bot.logger.error("Received unknown attachment "\
                                        f"of type '{type(a)}'")
            if notification and attachments and type(attachments[0]) == str:
                bot.rpc.send_msg(accid, rid, MsgData(text=notification,
                                                     file=attachments[0]))
                send_attachments(attachments[1:])
            elif notification:
                bot.rpc.send_msg(accid, rid, MsgData(text=notification))
                if attachments: send_attachments(attachments)
            elif attachments:
                send_attachments(attachments)
            else:
                bot.rpc.send_msg(accid, rid, MsgData(text="ping"))
    else:
        # If we encounter an unknown command at this point, we log an
        # error and simply treat the command as if it had been successful.
        c = script[pointer]["command"]
        bot.logger.error(f"Skipped unknown command '{c}' in"\
                         f" '{userdir}/script' at instruction {pointer}.")
    if script[pointer]["reply"].strip():
        reply = MsgData(text=script[pointer]["reply"])
        bot.rpc.send_msg(accid, chatid, reply)
        log_message(userdir, reply)
    advance_instruction_pointer(userdir)
    continue_execution(bot, accid, chatid, userdir, script)

def log_message(userdir: str, message) -> None:
    with open(f"{userdir}/conversation.log", "a") as f:
        print(message, file=f)

def validate_script(parsed_script: list[dict]) -> None:
    def check_subclauses(i: int, inst: dict, allowed_subclauses: list):
        for k in inst.keys():
            if k in ["command", "args", "reply"]: continue
            if k in allowed_subclauses: continue
            raise Exception(f"Error at instruction {i}: subclause {k} is "\
                            f"not allowed with command '{inst['command']}")
    # Validate the script semantics; otherwise raise an exception
    for i, inst in enumerate(parsed_script):
        # Check that "command" and "reply" exist. Note that their value
        # can still be the emtpy string.
        if not "command" in inst:
            raise Exception(f"Instruction {i} has no command")
        if not "reply" in inst:
            raise Exception(f"Instruction {i} has no reply")
        # Check that command is within a known set of commands and has
        # the expected arguments.
        if i == 0 and inst["command"] == "":
            pass    # This is allowed and results in the greeting message.
        elif inst["command"] == "wait-for":
            check_subclauses(i, inst, ["match", "otherwise"])
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
            check_subclauses(i, inst, ["otherwise"])
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
        elif inst["command"] == "notify":
            check_subclauses(i, inst, ["attach"])
            for item in inst.get("attach", []):
                if item not in ["contact.vcf", "chat_log.txt", "last-text",
                                "last-image", "last-voice", "media.zip",
                                "full_chat.zip"]:
                    raise Exception(f"Error at instruction {i}: "\
                                    f"Unknown attachment '{item}'")
            if len(inst["args"]) < 1:
                raise Exception(f"Error at instruction {i}: "\
                                 "'notify' takes at least one argument")
            elif inst["args"][0] != "admins":
                raise Exception(f"Error at instruction {i}: "\
                                 "only 'notify admins' is implemented so far")
        else:
            raise Exception(f"Error at instruction {i}: "\
                            f"Unknown command '{inst['command']}'")
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
        elif word in ["%command%", "%args%", "%reply%"]:
            raise Exception(f"Reserved word '{word}' used as subclause")
        elif word.startswith('%') and word.endswith('%') and len(word) > 2:
            context = word[1:-1]
            result[context] = []
        else:
            result[context].append(word)
    return result
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

def reset_admin_chat(cli, bot, args):
    """
    Resets the admin chat, which means that there will be a new invite
    link and a new empty admin group.
    """
    if not args.account:
        exit("The --account option is mandatory with reset_admin_chat")
    new_id = cli.reset_admin_chat(bot.rpc, args.account)
    print(f"Successfully created new admin chat with id {new_id}")
def list_admins(cli, bot, args):
    """
    List the members of the admin chat.
    """
    if not args.account:
        exit("The --account option is mandatory with list_admins")
    acc = bot.rpc.get_account_info(args.account)
    admins = bot.rpc.get_chat_contacts(args.account,
                                cli.get_admin_chat(bot.rpc, args.account))
    for admin_id in admins:
        a = bot.rpc.get_contact(acc.id, admin_id)
        if acc.addr == a.address and a.name == "Me": continue
        print(a.name_and_addr)

if __name__ == "__main__":
    cli.add_generic_option("--script",
                           help="Filename of the elissa script to use")
    cli.add_subcommand(reset_admin_chat)
    cli.add_subcommand(list_admins)
    try:
        cli.start()
    except KeyboardInterrupt:
        pass
