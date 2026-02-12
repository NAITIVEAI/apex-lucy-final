# Lucy Agent Portal User Guide

**Document Version**: 1.0
**Last Updated**: 2026-01-25
**Target Audience**: Apex customer service representatives, human agents
**Portal URL**: http://portal.apexclassaction.com

---

## Table of Contents

1. [Welcome to the Lucy Portal](#1-welcome-to-the-lucy-portal)
2. [Getting Started](#2-getting-started)
3. [Understanding the Handoff Process](#3-understanding-the-handoff-process)
4. [Receiving Escalation Notifications](#4-receiving-escalation-notifications)
5. [Joining a Conversation](#5-joining-a-conversation)
6. [Portal Interface Guide](#6-portal-interface-guide)
7. [Communicating with Users](#7-communicating-with-users)
8. [Accessing User Information](#8-accessing-user-information)
9. [Working with Documents](#9-working-with-documents)
10. [Closing a Conversation](#10-closing-a-conversation)
11. [The Callback System](#11-the-callback-system)
12. [Troubleshooting](#12-troubleshooting)
13. [Quality Assurance](#13-quality-assurance)
14. [Training & Support](#14-training--support)
15. [Frequently Asked Questions](#15-frequently-asked-questions)
16. [Appendix: Quick Reference](#16-appendix-quick-reference)
17. [Video Tutorial Script](#17-video-tutorial-script)

---

## 1. Welcome to the Lucy Portal

### What is the Lucy Portal?

The Lucy Agent Portal is a web-based application that allows you, as an Apex customer service representative, to seamlessly take over conversations from Lucy AI when human assistance is needed. Think of it as a bridge between our AI assistant and real human support.

**Key Benefits:**
- **Seamless Handoff**: Users don't have to repeat themselves when an agent joins
- **Full Context**: You see the entire conversation history before you join
- **Real-Time Chat**: Messages are delivered instantly between you and the user
- **Integrated Information**: Member details, documents, and case information all in one place
- **No Installation Required**: Access the portal directly from your web browser

### Who Should Use This Guide?

This guide is for you if you are:
- An Apex customer service representative
- A human agent providing member support
- Part of the escalation team for Lucy AI
- Training to handle escalated customer conversations

### What You'll Learn

By the end of this guide, you'll be able to:
- Recognize when Lucy has escalated a conversation to you
- Join live conversations with members
- Navigate the portal interface efficiently
- Communicate professionally with members
- Access member information and documents
- Handle callbacks when you're unavailable
- Troubleshoot common issues

---

## 2. Getting Started

### 2.1 Portal Access

#### How to Access the Portal

**Portal URL**: http://portal.apexclassaction.com

**Important**: Bookmark this URL in your browser for quick access. You'll be opening it frequently when responding to escalations.

#### Browser Compatibility

**Recommended Browsers** (Latest Versions):
- Google Chrome (recommended for best performance)
- Microsoft Edge
- Mozilla Firefox

**Not Supported**:
- Internet Explorer (any version)
- Safari on iOS (limited WebSocket support)
- Older browser versions (more than 2 years old)

#### Login Requirements

Currently, the portal uses header-based authentication. Your access is configured by the system administrator. If you encounter authentication issues, contact your IT support team.

#### First-Time Setup

1. **Bookmark the Portal**
   - Navigate to http://portal.apexclassaction.com/agent/portal
   - Press Ctrl+D (Windows) or Cmd+D (Mac) to bookmark
   - Name it "Lucy Agent Portal" for easy identification

2. **Test Your Access**
   - Click on your bookmark to open the portal
   - You should see the Agent Portal dashboard
   - If you see an error, contact your supervisor

3. **Configure Microsoft Teams**
   - Ensure you're logged into Microsoft Teams (desktop or web)
   - Join the "Lucy Escalations" channel
   - Enable desktop notifications for this channel

### 2.2 System Requirements

#### Required Software

**Microsoft Teams** (Desktop or Web):
- You'll receive escalation notifications through Teams
- Must have notifications enabled
- Must be a member of the "Lucy Escalations" channel

**Modern Web Browser**:
- Chrome 90+ (recommended)
- Edge 90+
- Firefox 88+

#### Network Requirements

**Connection Speed**: Minimum 5 Mbps download/upload

**Firewall Settings**: Your network must allow:
- WebSocket connections (wss://)
- HTTPS traffic to portal.apexclassaction.com
- Microsoft Teams notifications

**VPN**: If working remotely, ensure your VPN is connected before accessing the portal

### 2.3 Workspace Setup Recommendations

**Dual Monitor Setup** (Recommended):
- **Monitor 1**: Lucy Agent Portal (conversation interface)
- **Monitor 2**: Microsoft Teams, email, reference materials

**Single Monitor Alternative**:
- Use browser tabs for quick switching
- Keep Teams notifications visible
- Pin the portal tab for easy access

**Notification Settings**:
- Enable browser notifications for the portal
- Enable Teams desktop notifications
- Set Teams to "Available" when ready for escalations
- Set Teams to "Do Not Disturb" when unavailable

---

## 3. Understanding the Handoff Process

### 3.1 How Lucy Decides to Escalate

Lucy AI is designed to handle most member questions independently, but escalates to human agents when:

**1. Complex Questions**
- Questions requiring nuanced judgment
- Multi-step processes that need clarification
- Ambiguous situations without clear answers

**Example**: "I moved three times since submitting my claim. How do I update my address for all my settlements?"

**2. User Requests Human**
- User explicitly asks: "Can I speak to a person?"
- User expresses frustration with AI assistance
- User requests supervisor or manager

**Example**: "This isn't helping. I need to talk to a real person."

**3. System Limitations**
- Lucy cannot find relevant information
- Data sources are unavailable
- Authentication fails after multiple attempts

**Example**: Lucy tries multiple variations but can't authenticate the member's identity.

**4. Emotional Situations**
- User expresses distress, anger, or urgency
- Sensitive topics requiring empathy
- Situations needing careful handling

**Example**: "I desperately need this money. My electricity is getting shut off tomorrow."

### 3.2 The Handoff Flow

Here's what happens when Lucy decides to escalate a conversation to you:

```
┌─────────────────────────────────────────────────────────────┐
│ Step 1: Lucy Recognizes Need for Human                     │
│ - User requests human OR Lucy determines it's needed        │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 2: Lucy Checks Agent Availability                     │
│ - Queries Microsoft Teams for available agents             │
│ - Prioritizes by presence: Available > Busy > Idle         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 3: Teams Notification Sent                            │
│ - Adaptive Card sent to your Teams channel                 │
│ - Notification includes member ID, reason, conversation ID │
│ - 4-minute timer starts                                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 4: You Receive Notification                           │
│ - Teams pings you with notification sound                  │
│ - Card displays in "Lucy Escalations" channel              │
│ - Card shows member details and "Join Conversation" button │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 5: You Click "Join Conversation"                      │
│ - Portal opens in your browser                             │
│ - Conversation history loads automatically                 │
│ - WebSocket connection establishes                         │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 6: You Communicate with User                          │
│ - User sees: "Agent [Your Name] has joined the conversation"│
│ - You can see full conversation history                    │
│ - Real-time chat begins                                    │
└────────────────────┬────────────────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────────────────┐
│ Step 7: You Close the Conversation                         │
│ - Issue resolved or escalated further                      │
│ - You click "End Conversation"                             │
│ - Conversation archived for quality review                 │
└─────────────────────────────────────────────────────────────┘
```

### 3.3 What Lucy Tells the User

When Lucy escalates, the user sees a message like:

> "An APEX representative will join this chat within 5 minutes. If a representative is not able to join, please just reply back and I will set up a callback."

**Key Points:**
- **5-minute promise**: Users expect someone within 5 minutes (but you have 4 minutes before callback triggers)
- **Callback option**: If no agent joins, Lucy collects callback info automatically
- **User waits in same chat**: No need to call or start a new session

---

## 4. Receiving Escalation Notifications

### 4.1 Teams Adaptive Card

When Lucy escalates a conversation, you'll receive a notification in Microsoft Teams that looks like this:

**Visual Description**: [Screenshot placeholder - red/pink themed card with bold text]

**Card Components**:

**Header** (Red background, white text):
```
🚨 CUSTOMER HANDOFF REQUEST
```

**Important Notice** (Bold):
```
IMPORTANT: Do NOT reply in Teams. Use the Agent Portal link below.
```

**Member Information**:
- **Member ID**: APEX12345 (if authenticated)
- **Reason**: "User needs help with payment status"
- **Time**: 2026-01-25 10:30 UTC
- **Conversation ID**: conv-abc123... (truncated)

**Instructions**:
```
Click 'Join Conversation' below - customer is waiting
```

**Action Buttons**:
1. **Join Conversation NOW** (Red button) - Opens the portal
2. **View Agent Dashboard** (Secondary button) - Opens the queue

### 4.2 Understanding the 4-Minute Window

**Why 4 Minutes?**

The system gives you 4 minutes to join a conversation before automatically triggering the callback system. This ensures:
- Members don't wait indefinitely
- Backup plan if all agents are busy
- Service level agreement compliance

**Timeline**:
```
0:00 - Notification sent to Teams
0:30 - You should acknowledge (seen the notification)
1:00 - You should click "Join Conversation"
1:30 - Portal loads, you see conversation history
2:00 - You send first message to user
4:00 - TIMEOUT: If no agent joined, callback system activates
```

**What Happens at 4 Minutes (If You Don't Join)**:
1. Lucy receives timeout notification
2. Lucy says to user: "I apologize, but our agents are currently assisting other members. Let me collect your callback information."
3. Lucy asks for phone number and best time to call
4. Callback request created in system
5. You can call back when available (see Callback System section)

**Best Practice**: Aim to join within 90 seconds of receiving notification.

### 4.3 Urgency Indicators

**How to Recognize Priority**:

**High Priority** (Join immediately):
- Card theme color: Red (#D63384)
- Reason mentions: "urgent", "emergency", "immediate need"
- User has been waiting for previous callback

**Normal Priority**:
- Card theme color: Pink or orange
- General assistance requests
- Informational queries

**Multiple Notifications**:
- If you receive multiple notifications, join the oldest first
- Check timestamp in card to determine order
- Newer notifications may be handled by other agents

### 4.4 Notification Troubleshooting

**Not Receiving Notifications?**

Check these items:
1. **Teams Membership**: Confirm you're in "Lucy Escalations" channel
2. **Teams Notifications**: Ensure channel notifications are enabled
3. **Teams Presence**: Set status to "Available" (not "Do Not Disturb")
4. **Desktop Notifications**: Check Windows/Mac notification settings
5. **Focus Mode**: Disable if it's blocking Teams notifications

**Delayed Notifications?**

- Network latency may delay notifications by 5-15 seconds
- Refresh Teams if notifications seem stuck
- Contact IT if delays exceed 30 seconds consistently

---

## 5. Joining a Conversation

### 5.1 Step-by-Step: Joining a Conversation

**Step 1: Open Teams Notification**
1. Click on the notification in Teams (banner or channel message)
2. Review the member information shown in the card
3. Note the reason for escalation

**Step 2: Review Conversation Summary**
Read the card details:
- **Member ID**: Used to look up additional information
- **Reason**: Tells you what the member needs
- **Time**: Shows how long they've been waiting

**Step 3: Click "Join Conversation" Button**
1. Click the red "🔴 Join Conversation NOW" button
2. Portal opens in a new browser tab/window
3. Allow pop-ups if browser blocks the window

**Step 4: Portal Opens**
The portal automatically:
1. Loads the conversation page
2. Displays member information in the right sidebar
3. Shows conversation history in the center panel
4. Establishes WebSocket connection for real-time chat

**Step 5: WebSocket Connection Established**
You'll see:
- Green indicator dot (top right): "Connected"
- Status message: "Connected to conversation"
- Conversation history loads (Lucy's messages + user's messages)

**Step 6: Conversation History Loads**
The history shows:
- All messages between Lucy and the user
- Timestamps for each message
- System messages (e.g., "Lucy started the conversation")
- Tool executions (e.g., "Lucy searched for payment information")

**Step 7: You're Live with the User**
User sees in their chat:
```
🟢 Agent [Your Name] has joined the conversation.
```

You can now start communicating!

### 5.2 What You See When Portal Opens

**Screen Layout** (Three-panel design):

```
┌────────────────────────────────────────────────────────────────────┐
│  Lucy Agent Portal                             [Connected 🟢]      │
├──────────────────┬──────────────────────────────┬──────────────────┤
│                  │                              │                  │
│  Conversation    │      Active Chat             │  Context Panel   │
│  History Panel   │      Panel (Center)          │  (Right)         │
│  (Left)          │                              │                  │
│                  │                              │                  │
│  - Lucy: "Hello" │  ┌────────────────────────┐  │  Member Info:    │
│  - User: "Hi"    │  │                        │  │  - Name: John D. │
│  - Lucy: "How    │  │  [Message history]     │  │  - APEX ID: 123  │
│    can I help?"  │  │                        │  │  - Phone: ...    │
│  - User: "I need │  │                        │  │                  │
│    a person"     │  │                        │  │  Documents:      │
│                  │  │                        │  │  - Notice.pdf    │
│  [Auto-scrolls   │  │                        │  │                  │
│   to bottom]     │  │  [User is typing...]   │  │  Quick Actions:  │
│                  │  │                        │  │  - Save Note     │
│                  │  └────────────────────────┘  │  - Download      │
│                  │                              │    Transcript    │
│                  │  ┌────────────────────────┐  │                  │
│                  │  │ Type message...        │  │                  │
│                  │  │                        │  │                  │
│                  │  └────────────────────────┘  │                  │
│                  │  [Send] [End Conversation]   │                  │
└──────────────────┴──────────────────────────────┴──────────────────┘
```

**Panel Details**:

**Left Panel - Conversation History**:
- Scrollable history of all messages before you joined
- Color-coded: Lucy (blue), User (gray), System (light gray)
- Timestamps for each message
- Automatically scrolls to most recent

**Center Panel - Active Chat**:
- Real-time message area
- Your messages appear immediately
- User messages arrive with notification sound
- Typing indicators ("User is typing...")
- Message input box at bottom
- Send button or press Enter to send

**Right Panel - Context**:
- Member information (name, APEX ID, phone)
- Linked documents (notices, claims)
- Quick actions (save note, download transcript)
- Conversation metadata (start time, duration)

### 5.3 Initial Actions Checklist

When you first join a conversation, complete this checklist:

**Within First 30 Seconds**:
- [ ] Read the full conversation history
- [ ] Review the escalation reason
- [ ] Check member information sidebar
- [ ] Verify WebSocket is connected (green indicator)

**Within First 60 Seconds**:
- [ ] Send your first message to the user
- [ ] Acknowledge their issue
- [ ] Introduce yourself professionally

**Example First Message**:
```
Hi [User's Name], I'm [Your Name], an APEX representative. I can see that you need help with [reason from card]. I've reviewed your conversation with Lucy, so you don't need to repeat anything. How can I help you today?
```

### 5.4 Common Join Issues

**Portal Won't Open?**
- **Cause**: Pop-up blocker
- **Solution**: Allow pop-ups from Teams, then click button again

**Connection Failed?**
- **Cause**: Network/firewall issue
- **Solution**: Refresh page, check VPN connection

**History Not Loading?**
- **Cause**: Data retrieval delay
- **Solution**: Wait 5-10 seconds, refresh if still blank

**"Conversation Not Found"?**
- **Cause**: Invalid conversation ID or already closed
- **Solution**: Check if another agent already joined, contact supervisor

---

## 6. Portal Interface Guide

### 6.1 Main Components

#### 6.1.1 Conversation History Panel (Left)

**Purpose**: Shows the complete conversation between Lucy and the user before you joined.

**What You See**:

**Lucy's Messages** (Blue background):
```
Lucy:
Hello! I'm Lucy, your APEX AI assistant. I can help you with information about your settlement. May I have your member ID or the last 4 digits of your Social Security Number?
```

**User's Messages** (Gray background):
```
User:
my member id is APEX12345
```

**System Messages** (Light gray, italics):
```
System: Lucy authenticated member APEX12345
System: Lucy retrieved notice document for case ABC-2024
```

**Tool Calls** (Expandable):
```
[Tool] authenticate_member(apex_id="APEX12345")
[Result] Success: Authenticated John Doe
```

**Features**:
- **Auto-scroll**: Automatically jumps to most recent message
- **Timestamps**: Hover over message to see exact time
- **Search**: Ctrl+F to search within conversation
- **Expandable tool calls**: Click to see full details

**Why This Matters**:
- Prevents asking user to repeat information
- Shows what Lucy already tried
- Reveals user's emotional state
- Identifies patterns in the conversation

#### 6.1.2 Active Chat Panel (Center)

**Purpose**: Your primary workspace for communicating with the member in real time.

**Message Display Area**:

**Your Messages** (Green background):
```
Agent (You):
Hi John, I'm Sarah, an APEX representative. I can see you're asking about your payment status. Let me look that up for you right now.
```

**User Messages** (Gray background):
```
User:
Thank you! I've been waiting for weeks.
```

**Typing Indicators**:
```
User is typing...
```

**Message Input Box**:

**Features**:
- Multi-line text input (Shift+Enter for new line)
- Character counter (shows at 200+ characters)
- Markdown support (bold with `**text**`, italic with `_text_`)
- Emoji picker button (optional)

**Sending Messages**:
- **Method 1**: Click "Send" button
- **Method 2**: Press Enter (or Ctrl+Enter if configured)
- **Unsent messages**: Auto-saved if connection drops

**Message Status Indicators**:
- ⏳ Sending...
- ✓ Delivered
- ✓✓ Read by user (if supported)

#### 6.1.3 Context Panel (Right)

**Purpose**: Displays member information, documents, and quick actions.

**Member Information Section**:

```
👤 Member Information
━━━━━━━━━━━━━━━━━━━━━━
Name: John Michael Doe
APEX ID: APEX12345
Phone: (555) 123-4567
Email: john.doe@email.com
Status: Authenticated ✓

Settlement Cases:
• ABC Company Settlement (2024)
• XYZ Class Action (2023)
```

**Authenticated vs. Non-Authenticated**:

**Authenticated** (Green badge):
- Full name shown
- APEX ID verified
- All personal information visible
- Access to sensitive data

**Non-Authenticated** (Yellow badge):
- Limited information
- Only publicly available data
- Cannot access payment details
- Must verify identity before proceeding

**Documents Section**:

```
📄 Documents
━━━━━━━━━━━━━━━━━━━━━━
Notice Documents:
• ABC-Settlement-Notice.pdf (1.2 MB)
  Retrieved: 2026-01-25 10:15 AM

Claim Forms:
• Claim-Form-APEX12345.pdf (856 KB)
  Submitted: 2025-12-10
```

**Document Actions**:
- **View**: Opens PDF in new tab
- **Download**: Downloads to your computer
- **Share**: (Future feature) Send link to user

**Quick Actions**:

```
⚡ Quick Actions
━━━━━━━━━━━━━━━━━━━━━━
[Save Note to Profile]
[Download Transcript]
[Escalate to Supervisor]
[End Conversation]
```

**Button Functions**:
- **Save Note**: Adds note to member's Dynamics 365 profile
- **Download Transcript**: Downloads full conversation as text file
- **Escalate to Supervisor**: Creates high-priority ticket
- **End Conversation**: Closes chat and archives conversation

### 6.2 Navigation

#### 6.2.1 Switching Between Panels

**Desktop (Wide Screen)**:
- All three panels visible simultaneously
- No switching needed

**Tablet/Small Screen**:
- Swipe left/right to switch panels
- Tabs at top: History | Chat | Context

**Keyboard Shortcuts**:
- `Ctrl+1`: Focus conversation history
- `Ctrl+2`: Focus active chat (message input)
- `Ctrl+3`: Focus context panel
- `Ctrl+Enter`: Send message (from any panel)

#### 6.2.2 Minimizing/Maximizing Panels

**Minimize Left Panel** (Focus on chat):
- Click `◀` icon in panel header
- Panel collapses to narrow sidebar
- Click `▶` to expand again

**Maximize Center Panel** (Full-screen chat):
- Click `⛶` icon in chat header
- Left and right panels hide
- Press `Esc` to restore

**Hide Context Panel** (More chat space):
- Click `▶` icon in context panel header
- Panel slides to the right
- Click `◀` to restore

#### 6.2.3 Keyboard Shortcuts

**Message Composition**:
- `Enter`: Send message (default)
- `Shift+Enter`: New line in message
- `Ctrl+Enter`: Send message (alternate)
- `Esc`: Clear message draft

**Navigation**:
- `Ctrl+1`, `Ctrl+2`, `Ctrl+3`: Switch panels
- `Alt+H`: Jump to conversation history
- `Alt+M`: Focus message input
- `Alt+I`: Open member info

**Actions**:
- `Ctrl+N`: Save note
- `Ctrl+D`: Download transcript
- `Ctrl+E`: End conversation
- `Ctrl+/`: Show keyboard shortcuts help

#### 6.2.4 Accessibility Features

**Screen Reader Support**:
- All panels have ARIA labels
- Messages announce as they arrive
- Button labels clearly describe actions

**High Contrast Mode**:
- Automatically detects Windows High Contrast
- Increases border and text contrast
- Maintains color coding for message types

**Keyboard Navigation**:
- `Tab`: Move to next element
- `Shift+Tab`: Move to previous element
- `Enter`/`Space`: Activate buttons
- Full keyboard support (no mouse required)

**Font Size Adjustment**:
- Browser zoom works correctly (Ctrl + `+` / `-`)
- Text reflows properly at 200% zoom
- Maintains readability at all sizes

---

## 7. Communicating with Users

### 7.1 Best Practices

#### 7.1.1 Review Before Responding

**Before sending your first message, always:**

1. **Read the ENTIRE conversation history** (don't skim)
   - See what Lucy already told them
   - Understand what they've already tried
   - Identify their frustration points

2. **Check the escalation reason** (from Teams card)
   - Why did Lucy escalate?
   - What couldn't Lucy solve?
   - What does the user expect from you?

3. **Review member information** (context panel)
   - Are they authenticated?
   - Which settlements are they involved in?
   - Any previous notes on their account?

4. **Note what Lucy already tried**
   - Did Lucy search for documents?
   - Did authentication fail? Why?
   - Were there any tool errors?

**Example Bad Response** (didn't read history):
```
❌ Agent: Hi, can you provide your APEX ID so I can help you?
```
**Why it's bad**: User already provided APEX ID to Lucy. Now they feel frustrated.

**Example Good Response** (read history):
```
✓ Agent: Hi John, I'm Sarah from APEX. I can see you're asking about your payment status for the ABC Settlement. Lucy already looked up your information (APEX12345), so I have your details. Let me check the latest update on your payment right now.
```
**Why it's good**: Shows you read the conversation, uses their name, acknowledges what they already shared.

#### 7.1.2 Acknowledge the Handoff

**Always introduce yourself clearly:**

**Template**:
```
Hi [User's Name], I'm [Your Name], an APEX representative. I can see that [acknowledge their issue]. I've reviewed your conversation with Lucy, so you don't need to repeat anything. [Next step].
```

**Examples**:

**Example 1** (User requested human):
```
Hi Maria, I'm David, an APEX representative. I can see you asked to speak with a person. I've reviewed your conversation with Lucy about your payment timeline. Let me get you a specific answer on that right now.
```

**Example 2** (Complex issue):
```
Hi Robert, I'm Jennifer, an APEX representative. I can see you have questions about updating your address across multiple settlements. I've reviewed the details Lucy gathered, and I can walk you through the process step-by-step.
```

**Example 3** (Emotional situation):
```
Hi Susan, I'm Michael, an APEX representative. I understand this situation is urgent, and I'm here to help you get the information you need about your disbursement. Let me check the status right away.
```

#### 7.1.3 Don't Make Them Repeat Themselves

**Use information Lucy already collected:**

**What Lucy Gathers**:
- Member ID / APEX ID
- Name (if authenticated)
- Reason for contacting
- Settlement cases they're asking about
- Documents they need
- Previous attempts to get information

**Bad Example**:
```
❌ Agent: What's your member ID?
❌ Agent: Which settlement are you calling about?
❌ Agent: Can you describe the issue?
```
**Why**: Lucy already asked these questions. User gets frustrated.

**Good Example**:
```
✓ Agent: I can see you're asking about the ABC Settlement (APEX12345). Lucy was searching for your payment information. Let me pick up where Lucy left off.
```

**Exceptions** (When to re-ask):
- Lucy's authentication failed: "I see Lucy had trouble verifying your information. Let me try a different method. Can you confirm your date of birth?"
- Ambiguous situation: "Just to clarify, you mentioned two different settlements. Which one are you asking about specifically?"
- Security verification: "For your security, even though Lucy verified your APEX ID, I need to confirm your phone number before discussing payment details."

#### 7.1.4 Be Empathetic and Professional

**Show empathy**:
- Acknowledge their feelings: "I understand this is frustrating."
- Validate their concerns: "You're right to ask about that."
- Express care: "I'm here to make sure you get the help you need."

**Maintain professionalism**:
- Use proper grammar and spelling
- Avoid slang or overly casual language
- Stay calm, even if user is upset
- Never argue or become defensive

**Example Empathetic Responses**:

**User is frustrated**:
```
User: This is ridiculous! I've been waiting for weeks and nobody can tell me anything!

✓ Agent: I completely understand your frustration, and I apologize for the delay. You deserve clear answers. Let me look into your specific situation right now and get you accurate information.
```

**User is worried**:
```
User: I really need this money. Will I get it in time?

✓ Agent: I can see why this is important to you. Let me check the exact status of your disbursement and give you a realistic timeline. Give me just a moment to pull up the latest information.
```

**User is confused**:
```
User: I don't understand any of this. What does this notice even mean?

✓ Agent: I'm happy to explain this in simple terms. Let me break down what the notice is saying, step by step.
```

### 7.2 Message Composition

#### 7.2.1 Clear and Concise Language

**Write short, scannable messages:**

**Bad (too long)**:
```
❌ Agent: Thank you for contacting us today. I have reviewed your account and the information that Lucy was able to gather during your conversation, and I can see that you are inquiring about the status of your disbursement payment related to the ABC Company Settlement from 2024. I have checked our system and found that...
```

**Good (concise)**:
```
✓ Agent: I've checked your disbursement status. Your payment of $150.00 was mailed on January 20, 2026. It should arrive within 7-10 business days. Would you like me to provide the tracking information?
```

**Break long information into chunks:**

**Bad (wall of text)**:
```
❌ Agent: To update your address you need to log into the portal at www.abcsettlement.com and then click on "My Account" and then click "Update Information" and then enter your new address and make sure to click save and then you'll get a confirmation email.
```

**Good (step-by-step)**:
```
✓ Agent: Here's how to update your address:

1. Go to www.abcsettlement.com
2. Log in to your account
3. Click "My Account" → "Update Information"
4. Enter your new address
5. Click "Save"

You'll receive a confirmation email within 24 hours.
```

#### 7.2.2 Professional Tone

**Use professional, friendly language:**

**Professional Greeting**:
- ✓ "Hi [Name],"
- ✓ "Hello [Name],"
- ❌ "Hey there!"
- ❌ "What's up?"

**Professional Closings**:
- ✓ "Is there anything else I can help you with today?"
- ✓ "Let me know if you have any other questions."
- ❌ "Cool, we're done here."
- ❌ "Later!"

**Professional Phrases**:
- ✓ "I'd be happy to help with that."
- ✓ "Let me check that for you."
- ✓ "I understand your concern."
- ❌ "Yeah, sure, whatever."
- ❌ "Dunno, let me see."

#### 7.2.3 Proper Grammar and Spelling

**Always**:
- Use complete sentences
- Start sentences with capital letters
- End sentences with proper punctuation
- Spell out abbreviations (first use)

**Common Mistakes to Avoid**:

| ❌ Wrong | ✓ Right |
|---------|---------|
| "ur" | "your" |
| "dont" | "don't" |
| "gonna" | "going to" |
| "k" | "okay" or "I understand" |
| "cant" | "can't" |
| "alot" | "a lot" |
| "Its" | "It's" (contraction) or "Its" (possessive) |

**Use spell-check**: The message input box underlines spelling errors in red. Fix them before sending.

#### 7.2.4 Avoid Jargon

**Replace technical terms with plain language:**

| ❌ Jargon | ✓ Plain Language |
|-----------|------------------|
| "Your claim is in adjudication" | "We're currently reviewing your claim" |
| "Disbursement is pending ACH processing" | "Your payment is being processed and will arrive in 3-5 business days" |
| "You need to submit an affidavit of eligibility" | "You need to submit a form confirming you're eligible for this settlement" |
| "The class period is 2010-2020" | "This settlement covers anyone who was a customer between 2010 and 2020" |

**Explain when you must use technical terms:**

**Bad**:
```
❌ Agent: Your claim was submitted during the opt-out period, so it's been assigned to the CAFA subclass for pro rata distribution.
```

**Good**:
```
✓ Agent: Your claim was submitted during a specific time period called the "opt-out period." This means you'll be part of a smaller group that receives a share of the settlement. I can explain more about how the payment is calculated if you'd like.
```

### 7.3 Handling Difficult Situations

#### 7.3.1 User Frustration

**Recognize signs of frustration:**
- ALL CAPS messages
- Exclamation marks!!!
- Repeated questions
- Expressing anger or impatience

**Response Strategy:**

**Step 1: Acknowledge and validate**
```
✓ Agent: I completely understand your frustration. This situation has gone on longer than it should have, and I'm here to get you answers.
```

**Step 2: Take ownership**
```
✓ Agent: I apologize for the inconvenience this has caused you.
```

**Step 3: Provide immediate next step**
```
✓ Agent: Let me look into your account right now. I'll have an answer for you within 2 minutes.
```

**Step 4: Follow through quickly**
```
✓ Agent: I've checked your account. Here's what I found: [specific information]. [Next steps].
```

**Example Full Response:**
```
User: THIS IS RIDICULOUS! I'VE BEEN WAITING 6 WEEKS AND NOBODY KNOWS ANYTHING!!!

Agent: I completely understand your frustration. Six weeks is far too long to wait without clear information, and I apologize for that. I'm here to get you answers right now. Let me pull up your account and check the exact status of your payment. Give me just one moment.

[30 seconds later]

Agent: Thank you for waiting. I've found your payment information. Your check for $237.50 was mailed on January 15, 2026. USPS tracking shows it was delivered to your address on January 22. If you haven't received it, I can initiate a replacement check today. Would you like me to do that?
```

#### 7.3.2 Repeated Questions

**Why users repeat questions:**
- They didn't understand your previous answer
- The answer wasn't specific enough
- They don't believe the answer
- They're anxious and need reassurance

**Response Strategy:**

**Bad (just repeating the same answer)**:
```
❌ User: When will I get my check?
❌ Agent: Your check was mailed on January 15.
❌ User: But when will I GET it?
❌ Agent: It was mailed January 15.
```

**Good (more specific, addresses underlying concern)**:
```
✓ User: When will I get my check?
✓ Agent: Your check was mailed on January 15, 2026.
✓ User: But when will I GET it?
✓ Agent: Based on USPS delivery times, checks mailed on January 15 typically arrive within 7-10 business days. That means you should receive it between January 24-29. If it doesn't arrive by January 30, please contact us and we'll issue a replacement immediately. Does that help clarify the timeline?
```

**Rephrase with more detail:**
```
Agent: Let me be more specific about the timeline:
• January 15: Check mailed from processing center
• January 24-29: Expected delivery window
• January 30: If not received, we can issue replacement
• February 5: Replacement would arrive (if needed)

Does that give you a clearer picture?
```

#### 7.3.3 Technical Difficulties

**Common technical issues:**
- User can't see your messages
- User's messages not sending
- Portal freezing or slow
- Disconnect/reconnect issues

**Troubleshooting Steps:**

**Issue: "I'm not seeing your messages"**
```
Agent: Let me send you a test message. Can you see this? If so, please type "yes."

[User: yes]

Agent: Great! Our connection is working now. Let me continue with your question about...
```

**Issue: Portal is slow**
```
Agent: I'm noticing some delay in our connection. If you don't see my responses immediately, please wait 10-15 seconds. Your messages are getting through, there's just a slight delay. I'll keep helping you until we resolve your issue.
```

**Issue: Repeated disconnections**
```
Agent: I see we're having connection issues. If we get disconnected, I've saved all your information. You can close this window and I'll call you at (555) 123-4567 within 10 minutes to finish helping you. Does that work?
```

**Have a backup plan:**
- Offer to call them
- Provide your direct email
- Schedule a callback
- Escalate to supervisor if technology is blocking resolution

#### 7.3.4 Escalating Further if Needed

**When to escalate to a supervisor:**
- You can't resolve the issue with your authority level
- User is demanding to speak to a manager
- Situation requires approval beyond your role
- Potential legal or compliance concern
- User is making threats or using abusive language

**How to escalate:**

**Step 1: Acknowledge the need**
```
Agent: I understand this situation needs someone with more authority. Let me connect you with my supervisor who can help with this.
```

**Step 2: Use the "Escalate to Supervisor" button**
- Click "Escalate to Supervisor" in Quick Actions
- Fill in escalation form:
  - Reason for escalation
  - Summary of issue
  - What you've already tried
  - User's expected resolution

**Step 3: Set expectations**
```
Agent: I've created a priority escalation for you. A supervisor will join this chat within 5 minutes, or if they're unavailable, they'll call you within 1 hour at the number on your account. Is there anything else I can help you with while we wait?
```

**Step 4: Stay in the chat until supervisor joins** (or user agrees to callback)

---

## 8. Accessing User Information

### 8.1 Authenticated Users

**When a user is authenticated**, you have access to:

**Personal Information:**
- Full legal name
- APEX Member ID
- Contact phone number
- Email address
- Mailing address

**Case Information:**
- Settlements they're part of (ABC Settlement, XYZ Class Action)
- Claim status (Approved, Pending, Denied)
- Disbursement amounts
- Payment dates and methods

**Document Access:**
- Legal notices (PDFs)
- Claim forms (submitted and blank)
- Previous correspondence

**Previous Interactions:**
- Notes from previous agents
- Call history
- Email correspondence
- Previous chat transcripts

**Example Authenticated User Profile:**
```
👤 Member Information (Authenticated ✓)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Name: John Michael Doe
APEX ID: APEX12345
Phone: (555) 123-4567
Email: john.doe@email.com
Address: 123 Main St, Anytown, CA 90210

Settlement Cases:
• ABC Company Settlement (2024) - Claim Approved
  Payment: $237.50 (Mailed 01/15/2026)
• XYZ Class Action (2023) - Claim Pending Review
  Expected: $50.00 (Est. 03/2026)

Notes:
• 12/10/2025: Agent Sarah - User called about address change
• 11/15/2025: Agent David - Resent claim form via email
```

### 8.2 Non-Authenticated Users

**When a user is NOT authenticated**, you see limited information:

**What You Can See:**
- Conversation history with Lucy
- Reason for contact (from Teams card)
- Messages they've sent in this session
- Publicly available settlement information

**What You CANNOT See:**
- Full name (unless they volunteer it)
- APEX ID (unless they provide it)
- Personal contact information
- Payment details
- Claim status

**Example Non-Authenticated Profile:**
```
👤 Member Information (Not Authenticated ⚠️)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Status: Not Verified

Limited Information Available:
- Lucy could not verify identity
- User has not provided sufficient information

Available Actions:
- Verify identity manually
- Request member ID or last 4 of SSN
- Provide general information only
```

### 8.3 How to Verify Identity Manually

If Lucy couldn't authenticate the user, you can verify manually:

**Method 1: APEX ID**
```
Agent: To access your specific claim information, I'll need to verify your identity. Do you have your APEX Member ID? It starts with "APEX" followed by numbers.

User: APEX12345

Agent: Thank you. Let me verify that in our system.
[Manually search Dynamics 365 or internal system]
[Confirm name matches]

Agent: Thank you, John. I've verified your account. Now I can access your payment details.
```

**Method 2: Last 4 of SSN + Date of Birth**
```
Agent: I can help you with that. For security, can you provide the last 4 digits of your Social Security Number and your date of birth?

User: 1234 and 05/15/1980

Agent: Thank you. Let me verify that information.
[Manually look up in system]
[Confirm match]

Agent: I've verified your identity. I can now see your account details.
```

**Method 3: Case Number + Name**
```
Agent: Do you have the case number from the notice you received? It usually starts with "Case No." or is at the top of the letter.

User: Case No. ABC-2024-12345

Agent: And can you confirm your full legal name as it appears on the notice?

User: John Michael Doe

Agent: Thank you. Let me verify that.
[Look up case and confirm name]

Agent: I've located your claim in the ABC Settlement. Now I can help you with your question.
```

### 8.4 When to Request Additional Information

**Request additional info when:**
- User asks about payment details (requires authentication)
- User wants to update personal information (requires verification)
- User is asking about a specific claim (need to verify it's theirs)
- You need to access restricted information

**DON'T request additional info when:**
- User is asking general questions about the settlement
- User wants to know how to file a claim (public information)
- User is asking about deadlines or eligibility criteria
- Information is publicly available on the settlement website

**Example: General Question (No Auth Needed)**
```
User: What is the ABC Settlement about?

Agent: The ABC Settlement is a class action lawsuit against ABC Company for overcharging customers between 2018-2020. Members who were customers during that time may be eligible for payments of $50-$500. No verification needed for general information. Would you like to know how to check if you're eligible?
```

**Example: Specific Question (Auth Required)**
```
User: Has my payment been sent?

Agent: I'd be happy to check that for you. To access your payment information, I need to verify your identity. Do you have your APEX Member ID, or I can verify using the last 4 digits of your Social Security Number?
```

---

## 9. Working with Documents

### 9.1 Viewing Notices

**When Lucy has already retrieved a notice:**

Lucy may have already found and displayed the relevant PDF to the user. You'll see this in the conversation history:

```
System: Lucy retrieved document: ABC-Settlement-Notice.pdf
```

The document will also appear in the **Context Panel (Right)** under "Documents":

```
📄 Documents
━━━━━━━━━━━━━━━━━━━━━━
Notice Documents:
• ABC-Settlement-Notice.pdf (1.2 MB)
  Retrieved: 2026-01-25 10:15 AM
  [View] [Download]
```

**How to view:**
1. Click "View" button
2. PDF opens in new browser tab
3. Review the notice to answer user's question
4. Return to portal tab to continue chat

**How to download (for offline reference):**
1. Click "Download" button
2. PDF downloads to your Downloads folder
3. Rename if needed for easy identification

### 9.2 Searching for Documents

**If the notice was NOT already retrieved**, you can search for it:

**Method 1: Use APEX ID**
```
Agent: Let me find your notice. I'll search using your APEX ID (APEX12345).
[Use internal system or search tool]
[Locate document]
[Share with user]

Agent: I've found your notice for the ABC Settlement. I'm viewing it now. What specific information do you need from it?
```

**Method 2: Use Case Number**
```
Agent: Can you provide the case number from your notice? It's usually at the top.

User: ABC-2024-12345

Agent: Thank you. Let me search for that document.
[Search by case number]
[Verify document matches user]

Agent: I've located the notice. Let me find the answer to your question.
```

**Method 3: Use Settlement Name + Date Range**
```
Agent: Do you remember approximately when you received the notice? And which settlement it's for?

User: It was about the ABC Company case, I got it in November 2025

Agent: Perfect. Let me search for ABC Settlement notices from November 2025.
[Search with date filter]
[Find matching document]

Agent: I found a notice that matches. To make sure it's yours, can you confirm your name is on it? I'll read you the first few names...
```

### 9.3 Verifying Document Accuracy

**Always verify the document matches the user before sharing details:**

**Checklist:**
- [ ] User's name appears on the notice
- [ ] APEX ID matches (if visible on notice)
- [ ] Settlement name matches what user asked about
- [ ] Document date is recent (not expired settlement)

**If document doesn't match:**
```
Agent: I found a document, but I want to make sure it's the right one. The notice I'm looking at is for the ABC Settlement, dated January 2024. Is that the one you're asking about?

User: No, mine is from 2025

Agent: Thank you for clarifying. Let me search for the 2025 notice instead.
```

**If multiple documents exist:**
```
Agent: I found two notices for ABC Settlement on your account:
1. Original notice (January 2024) - Claim deadline was June 2024
2. Updated notice (November 2025) - Extended deadline is March 2026

Which one are you asking about?
```

### 9.4 Explaining Documents to Users

**Users often struggle with legal language in notices. Help them understand:**

**Break down complex sections:**

**Bad (just quote the notice)**:
```
❌ Agent: The notice says: "Class members who submit valid claims shall receive pro rata distribution of the net settlement fund after deduction of attorney fees, costs, and administrative expenses, not to exceed the aggregate of approved claims."
```

**Good (explain in simple terms)**:
```
✓ Agent: Here's what the notice means in simple terms:

If you submit a valid claim, you'll get a portion of the settlement money. The total amount is divided among all approved claims. Before payments go out, the lawyers' fees and processing costs are deducted.

The exact amount depends on how many people file claims, but estimates are between $50-$300 per person.
```

**Highlight key dates and actions:**

```
Agent: The most important information in your notice:

• Claim Deadline: March 15, 2026 (you have 2 months to file)
• What you need to do: Fill out the claim form online or mail it
• Expected payment: Summer 2026 (if claim approved)
• Claim form: I can email it to you or you can download it from [website]

Would you like me to walk you through how to fill out the claim form?
```

**Answer specific questions about the notice:**

```
User: What does "class period" mean?

Agent: Great question. The "class period" is the time range when you had to be a customer to be eligible. For the ABC Settlement, the class period is January 2018 - December 2020. If you were a customer anytime during those 3 years, you're eligible to file a claim.
```

### 9.5 Sharing Documents with Users

**How to share PDFs with users:**

**Method 1: Direct download link (if supported)**
```
Agent: I can send you a direct link to download the notice. Would you like me to do that?

[Click "Share Document" button]
[System generates temporary download link]

Agent: Here's the link: https://portal.apexclassaction.com/documents/abc-notice-APEX12345.pdf

This link will work for 24 hours. Let me know if you have trouble accessing it.
```

**Method 2: Email (if user is authenticated)**
```
Agent: I can email the notice to the address we have on file (john.doe@email.com). Would you like me to send it?

User: Yes please

[Click "Email Document" button]
[Confirm email sent]

Agent: I've sent the notice to your email. It should arrive within a few minutes. Check your spam folder if you don't see it.
```

**Method 3: Describe how to access on settlement website**
```
Agent: You can also download the notice yourself from the official settlement website:

1. Go to www.abcsettlement.com
2. Click "View My Notice"
3. Enter your APEX ID: APEX12345
4. Click "Download Notice"

Let me know if you'd prefer I email it instead.
```

---

## 10. Closing a Conversation

### 10.1 When to Close

**Close the conversation when:**
- ✓ User's question has been fully answered
- ✓ User confirms they're satisfied
- ✓ User says goodbye or thanks you
- ✓ User has no further questions
- ✓ Issue has been escalated and user is aware
- ✓ Callback has been scheduled and confirmed

**DO NOT close when:**
- ❌ User is still asking questions
- ❌ You promised to check something and haven't reported back
- ❌ User seems confused or uncertain
- ❌ Issue is partially resolved but user needs follow-up
- ❌ User hasn't responded in <2 minutes (they may be typing)

### 10.2 How to Close a Conversation

**Step 1: Confirm Resolution**

Ask if the user is satisfied before closing:

```
Agent: I've provided you with the payment tracking information and emailed you a copy of the notice. Is there anything else I can help you with today?
```

Wait for user response:

**If user says "No, that's all" or "Thank you":**
```
Agent: You're very welcome! If you have any other questions in the future, feel free to contact us anytime. Have a great day!

[Now you can close]
```

**If user says "Yes, one more thing":**
```
Agent: Of course! What else can I help you with?

[Continue conversation]
```

**If user doesn't respond:**

Wait 2-3 minutes, then send:
```
Agent: I haven't heard back from you. I'll stay connected for another few minutes in case you have questions. If I don't hear from you, I'll close this conversation, but you can always contact us again if you need anything else.
```

Wait another 2 minutes. If still no response, you can close.

**Step 2: Click "End Conversation" Button**

1. Click the "End Conversation" button (bottom right of Active Chat panel)
2. A confirmation dialog appears:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 End Conversation?

 Are you sure you want to end this conversation?
 This will close the chat and archive the transcript.

 [Add Closing Note (Optional)]
 ┌────────────────────────────────┐
 │ User satisfied with payment    │
 │ tracking info. No further      │
 │ assistance needed.             │
 └────────────────────────────────┘

       [Cancel]    [End Conversation]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Step 3: Add Closing Note (Optional)**

The closing note is for internal records and quality assurance. It helps supervisors understand how the conversation ended.

**Good closing notes:**
- "User satisfied. Provided payment tracking and notice PDF."
- "Escalated to supervisor for approval on payment reissue."
- "Scheduled callback for tomorrow at 2pm PST."
- "User's issue resolved. No further action needed."

**Bad closing notes:**
- "Done" (too vague)
- "User left" (doesn't explain resolution)
- "" (blank - doesn't document outcome)

**Step 4: Click "End Conversation"**

After clicking:
1. User sees: "Agent [Your Name] has ended the conversation. Thank you for contacting APEX."
2. Portal shows: "Conversation Ended" confirmation
3. Conversation is archived
4. You're redirected to the Agent Portal dashboard

### 10.3 After Closing

**Conversation is automatically:**
- Archived to Azure Tables storage
- Available for review by supervisors
- Stored for 30 days (Foundry conversation retention policy)
- Accessible for quality assurance review

**User can:**
- Download transcript (if feature is enabled)
- Start a new conversation with Lucy if they have more questions
- See the conversation in their history (if authenticated)

**You can:**
- View transcript in "Past Conversations" (if you have access)
- Refer to it if user contacts again about same issue
- Use it for training or quality review

### 10.4 What Happens if User Leaves Without Warning

**User disconnects unexpectedly** (closes browser, loses internet, etc.):

**You'll see:**
```
System: User disconnected
```

**What to do:**

**Option 1: Wait 2 minutes**
```
[Wait to see if user reconnects]
```
User may have lost connection temporarily and is trying to get back.

**Option 2: Send final message**
```
Agent: It looks like we've lost connection. If you're still there and need more help, please send a message. Otherwise, I'll close this conversation in 2 minutes.
```

**Option 3: Create callback**
```
If user was in the middle of an important issue:
1. Click "Create Callback"
2. Fill in callback form:
   - User's phone number (from profile)
   - Reason: "Disconnected during conversation about payment issue"
   - Best time: "ASAP"
3. Call user back within 30 minutes
```

**Option 4: End conversation with note**
```
After 2-3 minutes of no response:
1. Click "End Conversation"
2. Add note: "User disconnected during conversation. Issue partially resolved. Recommend callback if user contacts again."
```

---

## 11. The Callback System

### 11.1 Understanding Callbacks

**What is a callback?**

A callback is a request for an agent to call a member back when no agent was available to join the live chat within the 4-minute window.

**How callbacks are created:**

**Automatic (Timeout)**:
1. Lucy escalates conversation to agents
2. 4-minute timer starts
3. No agent joins within 4 minutes
4. Lucy says to user: "I apologize, but our agents are currently assisting other members. Let me collect your callback information."
5. Lucy collects phone number and best time to call
6. Callback request created in system

**Manual (Agent creates)**:
1. Agent is in conversation with user
2. Issue requires research or escalation
3. Agent creates callback request
4. User agrees to be called back later

### 11.2 Callback Request Details

**What's included in a callback request:**

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Callback Request #CB-550e8400

 Created: 2026-01-25 10:45 AM PST
 Status: Pending

 Member Information:
 - Name: John Doe
 - APEX ID: APEX12345
 - Phone: (555) 123-4567

 Callback Details:
 - Best Time: PST 9am-5pm
 - Reason: User needs help with payment status
 - Priority: Normal

 Original Conversation:
 - Conversation ID: conv-abc123...
 - Lucy tried to help but user requested human
 - Lucy could not authenticate member
 - User provided APEX ID: APEX12345

 [View Full Transcript] [Complete Callback]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 11.3 How to View Pending Callbacks

**Step 1: Navigate to Callbacks Page**
1. Go to http://portal.apexclassaction.com/agent/callbacks
2. Or click "Callbacks" in the top navigation menu

**Step 2: Review Callback List**

The Callbacks page shows:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Pending Callbacks (5)                [Refresh] [Export]

 ┌──────────┬────────────┬─────────────┬──────────┬────────┐
 │ Created  │ Member     │ Phone       │ Reason   │ Action │
 ├──────────┼────────────┼─────────────┼──────────┼────────┤
 │ 10:45 AM │ John Doe   │ 555-123-    │ Payment  │ [Call] │
 │          │ APEX12345  │ 4567        │ status   │        │
 ├──────────┼────────────┼─────────────┼──────────┼────────┤
 │ 11:20 AM │ Jane Smith │ 555-987-    │ Address  │ [Call] │
 │          │ APEX67890  │ 6543        │ update   │        │
 ├──────────┼────────────┼─────────────┼──────────┼────────┤
 │ 11:45 AM │ Bob Jones  │ 555-555-    │ General  │ [Call] │
 │          │ Not Auth   │ 5555        │ question │        │
 └──────────┴────────────┴─────────────┴──────────┴────────┘
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Sorting**:
- Click column headers to sort
- Default: Oldest first (top priority)

**Filtering**:
- "Show only my callbacks" (callbacks you created)
- "Show high priority only"
- "Show last 24 hours"

### 11.4 Handling Callbacks

**Step 1: Select a Callback**

Click on a callback row to expand details:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Callback Request #CB-550e8400

 Member: John Doe (APEX12345)
 Phone: (555) 123-4567
 Best Time: PST 9am-5pm (Anytime during business hours)
 Reason: User needs help with payment status

 Background:
 - User contacted Lucy at 10:30 AM
 - Lucy tried to authenticate but user couldn't remember SSN
 - User requested to speak with person
 - No agents available within 4-minute window
 - Lucy collected callback information

 Conversation Transcript:
 [Lucy]: Hello! I'm Lucy, your APEX AI assistant...
 [User]: I need to check my payment status
 [Lucy]: I'd be happy to help. May I have your APEX ID?
 [User]: APEX12345
 [Lucy]: Thank you. For verification, can you provide...
 [User]: I don't remember. Can I just talk to someone?
 [Lucy]: Of course. Let me connect you with a representative...
 [System]: No agents available. Callback requested.

 [View Full Transcript] [Call Now] [Schedule Later] [Cancel]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

**Step 2: Review the Transcript**

Click "View Full Transcript" to see:
- Complete conversation between Lucy and user
- What Lucy already tried
- User's exact question
- Why authentication failed (if applicable)

**Step 3: Call the Member**

**Using your phone:**
1. Dial the phone number shown
2. Have the conversation transcript open for reference
3. Have the portal open to access member information

**Greeting:**
```
You: "Hello, this is [Your Name] from APEX Class Action Services. I'm calling for [Member Name]. Is this a good time to talk?"

Member: "Yes, this is [Name]."

You: "Great! I'm calling because you reached out to our AI assistant Lucy earlier today about [reason from callback]. Lucy collected some information from you, so I have context on your question. How can I help you?"
```

**Step 4: Resolve the Issue**

Handle the callback like you would any conversation:
- Verify identity if needed (APEX ID, SSN, etc.)
- Answer their question
- Provide clear next steps
- Confirm they're satisfied

**Step 5: Complete the Callback**

After the call:

1. Click "Complete Callback" button
2. Fill in callback completion form:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 Complete Callback

 Did you reach the member?
 ● Yes, spoke with member
 ○ No answer (voicemail left)
 ○ Wrong number
 ○ Member requested later callback

 Outcome:
 ● Issue resolved
 ○ Escalated to supervisor
 ○ Additional research needed
 ○ Scheduled follow-up

 Agent Notes:
 ┌────────────────────────────────┐
 │ Spoke with John Doe. Verified  │
 │ identity via APEX ID. Provided │
 │ payment tracking info. Payment │
 │ of $237.50 mailed 01/15/2026.  │
 │ User satisfied. No further     │
 │ action needed.                 │
 └────────────────────────────────┘

 Save note to member profile?
 ☑ Yes, add to Dynamics 365

       [Cancel]    [Mark Complete]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

3. Click "Mark Complete"
4. Callback is archived
5. Note is saved to member's profile (if selected)

### 11.5 Callback Best Practices

**DO:**
- ✓ Handle callbacks within 1 hour of creation (when possible)
- ✓ Leave voicemail if no answer (with your name and callback number)
- ✓ Review the transcript before calling (don't make user repeat themselves)
- ✓ Add detailed notes when completing callback
- ✓ Save important notes to member profile

**DON'T:**
- ❌ Let callbacks sit for days without attempting contact
- ❌ Call outside of member's preferred time
- ❌ Ask questions Lucy already asked
- ❌ Leave vague notes like "Called user" without outcome
- ❌ Close callback without documenting what happened

**Voicemail Script:**
```
"Hello, this is [Your Name] from APEX Class Action Services. I'm calling for [Member Name] regarding your recent inquiry about [reason]. We attempted to connect you with a live agent earlier, but all agents were busy. Please call us back at 1-800-XXX-XXXX, or I'll try you again [tomorrow/this afternoon]. Thank you."
```

### 11.6 Canceling or Rescheduling Callbacks

**To cancel a callback** (if it's a duplicate or no longer needed):
1. Open callback details
2. Click "Cancel Callback"
3. Provide reason:
   - "Duplicate request"
   - "Member called back and issue resolved"
   - "Member requested cancellation"
   - "No longer needed"
4. Confirm cancellation

**To reschedule a callback**:
1. Open callback details
2. Click "Reschedule"
3. Select new date/time
4. Add note: "Member requested callback on [date] at [time]"
5. Save

---

## 12. Troubleshooting

### 12.1 Common Issues

#### Issue: Can't Join Conversation

**Symptoms:**
- "Join Conversation" button doesn't work
- Portal opens but shows error
- Stuck on "Loading..." screen

**Causes:**
1. Pop-up blocker preventing portal from opening
2. Browser compatibility issue
3. Conversation already closed/taken by another agent
4. Network connectivity problem

**Solutions:**

**Step 1: Check pop-up blocker**
```
Chrome:
1. Click the pop-up blocked icon in address bar
2. Select "Always allow pop-ups from teams.microsoft.com"
3. Click "Join Conversation" button again

Edge:
1. Click the pop-up blocked icon in address bar
2. Select "Always allow"
3. Try again

Firefox:
1. Go to Settings → Privacy & Security
2. Find "Pop-ups and redirects"
3. Add exception for teams.microsoft.com
4. Try again
```

**Step 2: Try different browser**
```
If using Edge, try Chrome
If using Firefox, try Edge
Recommended: Chrome (latest version)
```

**Step 3: Refresh and retry**
```
1. Close the portal tab (if it opened)
2. Go back to Teams notification
3. Click "Join Conversation" again
```

**Step 4: Check if conversation is still active**
```
1. Go to http://portal.apexclassaction.com/agent/portal
2. Look in "Pending Conversations" list
3. If conversation is not listed, it was already taken or closed
4. Check with team to see if another agent joined
```

**Step 5: Contact IT support**
```
If none of the above work:
1. Take screenshot of error message
2. Note: conversation ID, time, browser version
3. Contact IT helpdesk
4. Continue with next pending conversation
```

#### Issue: No Conversation History

**Symptoms:**
- Portal opens but conversation history panel is blank
- Shows "Loading..." indefinitely
- Error message: "Failed to load conversation history"

**Causes:**
1. Azure Storage connection issue
2. Conversation ID mismatch
3. Data not yet synced
4. Browser cache problem

**Solutions:**

**Step 1: Wait 10 seconds**
```
Sometimes history takes a few seconds to load
Look for loading indicator
If it says "Loading...", wait up to 15 seconds
```

**Step 2: Refresh the page**
```
1. Press F5 (Windows) or Cmd+R (Mac)
2. Portal reconnects and tries to load history again
```

**Step 3: Check browser console for errors** (Advanced)
```
1. Press F12 to open developer tools
2. Click "Console" tab
3. Look for red error messages
4. Take screenshot and send to IT support
```

**Step 4: Continue without history (temporary workaround)**
```
If history won't load but user is waiting:
1. Send message to user: "Hi, I'm an APEX representative joining this conversation. I'm having a technical issue viewing our previous conversation. Can you briefly remind me what you need help with?"
2. User will re-explain (not ideal, but ensures they get help)
3. Resolve their issue
4. Report the technical problem to IT after conversation ends
```

#### Issue: User Not Responding

**Symptoms:**
- You send messages but user doesn't reply
- User's last message was several minutes ago
- No "typing..." indicator

**Possible Reasons:**
1. User stepped away from computer
2. User closed their browser
3. User lost internet connection
4. User is typing a long response
5. User thinks conversation is over

**What to Do:**

**Step 1: Wait 2-3 minutes**
```
User may be:
- Looking for documents
- Writing a long response
- Distracted by something
```

**Step 2: Send gentle follow-up**
```
Agent: "I'm still here if you have any questions. Let me know if you need anything else."
```

**Step 3: Check connection status**
```
Look at top right of portal:
- Green dot: Connected
- Yellow dot: Connection unstable
- Red dot: Disconnected

If disconnected, user may have lost connection
```

**Step 4: Wait another 2 minutes after follow-up**
```
Total wait time: 4-5 minutes before taking action
```

**Step 5: Send final message**
```
Agent: "I haven't heard back from you. I'll stay connected for another few minutes in case you have questions. If I don't hear from you, I'll close this conversation, but you can always contact us again if you need anything else."
```

**Step 6: If still no response after 2 more minutes**
```
1. Click "End Conversation"
2. Add note: "User stopped responding. Issue partially resolved. Available for follow-up if user contacts again."
3. Move to next pending conversation
```

#### Issue: WebSocket Disconnection

**Symptoms:**
- Red "Disconnected" indicator in top right
- Error message: "Connection lost. Attempting to reconnect..."
- Messages not sending

**Causes:**
1. Internet connection dropped
2. Network firewall blocked WebSocket
3. Server-side issue
4. Browser closed connection

**Solutions:**

**Automatic Reconnection** (Portal tries this first):
```
Portal automatically attempts to reconnect:
- Attempt 1: Immediate
- Attempt 2: After 2 seconds
- Attempt 3: After 4 seconds
- Attempt 4: After 8 seconds
- Attempt 5: After 16 seconds

If successful, you'll see:
✓ "Reconnected successfully"
[Continue conversation normally]
```

**Manual Reconnection**:
```
If automatic reconnection fails:
1. Refresh the page (F5 or Cmd+R)
2. Portal re-establishes WebSocket
3. Conversation history reloads
4. Continue conversation
```

**If refresh doesn't work**:
```
1. Close portal tab
2. Go back to Teams notification
3. Click "Join Conversation" again
4. Portal opens fresh connection
```

**If still can't reconnect**:
```
1. Check your internet connection
2. Try accessing another website
3. If internet is fine, check VPN connection
4. Contact IT support
5. Call user as backup (use phone number from member profile)
```

#### Issue: Can't Access Documents

**Symptoms:**
- PDF won't load when clicking "View"
- "Download" button doesn't work
- Error: "Document not found"

**Causes:**
1. Document doesn't exist in storage
2. APEX ID incorrect
3. Permissions issue
4. Storage service down

**Solutions:**

**Step 1: Verify APEX ID**
```
Double-check APEX ID in member profile
Try searching again with correct ID
```

**Step 2: Search by alternative method**
```
Instead of APEX ID, try:
- Case number
- Member name + settlement name
- Date range
```

**Step 3: Check if document exists**
```
Ask user:
"Can you confirm you received a notice by mail or email? Do you have the notice with you?"

If user says no:
"Let me check if a notice has been mailed to you yet. What's your address on file?"
```

**Step 4: Use alternative access**
```
If PDF won't load in portal:
1. Access internal document system directly
2. Search for document there
3. Download locally
4. Summarize key information for user verbally
```

**Step 5: Escalate to technical support**
```
If document should exist but can't be accessed:
1. Document the issue (conversation ID, APEX ID, settlement name)
2. Help user with verbal information in the meantime
3. Report to IT after conversation
4. Offer to email document later when issue is fixed
```

### 12.2 Browser-Specific Issues

#### Google Chrome

**Issue: WebSocket connections blocked**
```
Solution:
1. Go to chrome://settings/content/insecureContent
2. Add portal.apexclassaction.com to "Allow" list
3. Restart browser
```

**Issue: Notifications not showing**
```
Solution:
1. Go to chrome://settings/content/notifications
2. Find portal.apexclassaction.com
3. Set to "Allow"
4. Refresh portal
```

#### Microsoft Edge

**Issue: Pop-ups blocked**
```
Solution:
1. Click the pop-up icon in address bar
2. Select "Always allow pop-ups and redirects from..."
3. Reload page
```

**Issue: WebSocket connection fails**
```
Solution:
1. Check Edge security settings
2. Ensure "Enhanced security" is not blocking WebSockets
3. Add exception for portal.apexclassaction.com
```

#### Mozilla Firefox

**Issue: Connection security warning**
```
Solution:
1. Click "Advanced" on warning page
2. Click "Accept the Risk and Continue"
3. Add permanent exception
```

**Issue: WebSocket connections unstable**
```
Solution:
1. Type about:config in address bar
2. Search for network.websocket
3. Ensure network.websocket.enabled is true
4. Restart Firefox
```

### 12.3 Getting Technical Support

**When to contact IT support:**
- Portal won't load after trying all solutions
- Persistent connection issues
- Error messages you don't understand
- Account/permission issues
- Security warnings

**What information to provide:**
```
When contacting IT, provide:

1. Your name and employee ID
2. Conversation ID (if applicable)
3. Time and date of issue
4. Browser and version
5. Exact error message
6. Screenshot of error
7. Steps you've already tried

Example email:

Subject: Portal Technical Issue - Can't Join Conversation

Hi IT Team,

I'm experiencing an issue with the Lucy Agent Portal.

Details:
- Name: Sarah Johnson
- Time: 2026-01-25 11:30 AM PST
- Issue: Can't join conversation
- Error: "WebSocket connection failed"
- Conversation ID: conv-abc123xyz
- Browser: Chrome 120.0.6099.199

Steps I tried:
- Refreshed page
- Tried different browser (Edge)
- Disabled pop-up blocker
- Checked internet connection (working fine)

Screenshot attached.

Please advise.

Thank you,
Sarah
```

**IT Support Contact:**
- Email: it-support@apexclass action.com
- Phone: (555) 100-2000
- Teams: @IT-HelpDesk
- Ticket System: http://helpdesk.internal

---

## 13. Quality Assurance

### 13.1 Performance Metrics

Your performance as an agent is measured by several key metrics:

#### Response Time
**Definition**: Time from when you join conversation to when you send your first message

**Target**: < 30 seconds

**Best Practice**:
- Join conversation immediately when you see notification
- Quickly scan conversation history (15-20 seconds)
- Send first message within 30 seconds

**Example Timeline**:
```
0:00 - Notification received
0:10 - Click "Join Conversation"
0:15 - Portal opens
0:25 - Read conversation history
0:30 - Send first message ✓
```

#### Resolution Rate
**Definition**: Percentage of conversations you resolve without needing to escalate

**Target**: > 80%

**What Counts as Resolved**:
- User's question answered
- User confirms satisfaction
- Next steps clearly communicated
- User has no further questions

**What Counts as Escalation**:
- Transferred to supervisor
- Created ticket for technical team
- Issue beyond your authority to resolve

**How to Improve**:
- Use available tools (search, Dynamics 365, documents)
- Ask clarifying questions
- Provide complete answers
- Verify user understands before closing

#### Customer Satisfaction
**Definition**: User rating of conversation (if they complete post-chat survey)

**Target**: > 4.5 out of 5

**Survey Questions** (Users see after conversation ends):
1. How satisfied were you with the assistance you received? (1-5 stars)
2. Did the agent resolve your issue? (Yes/No)
3. Was the agent professional and courteous? (Yes/No)
4. Additional comments (optional)

**How to Improve**:
- Be friendly and professional
- Show empathy
- Explain clearly
- Follow through on promises
- End on a positive note

#### Escalation from Portal to Supervisor
**Definition**: How often you need to escalate to a supervisor

**Target**: < 20% of conversations

**Valid Escalations** (Don't count against you):
- User demands to speak to manager
- Issue requires approval beyond your authority
- Legal or compliance concern
- Technical issue preventing resolution

**Avoidable Escalations** (Try to minimize):
- Didn't use available tools to find information
- Didn't attempt to resolve before escalating
- Gave up too quickly
- Misunderstood what user needed

### 13.2 Best Practices for High Performance

#### Be Proactive
```
❌ Bad: Waiting for user to ask follow-up questions

✓ Good: Anticipate what they'll need next

Example:
User: "When will my payment arrive?"
Agent: "Your payment of $237.50 was mailed on January 15, 2026. Based on USPS delivery times, you should receive it by January 29. If you don't receive it by February 1, please contact us and we'll issue a replacement. I can also email you the tracking information if you'd like. Would that be helpful?"
```

#### Set Clear Expectations
```
❌ Bad: "I'll check on that"

✓ Good: "Let me check that for you. It will take about 2 minutes."

Example:
Agent: "I'm going to search our system for your payment information. This will take about 60 seconds. Please wait just a moment."
[User knows how long to wait]
[You deliver answer in 60 seconds or less]
```

#### Follow Through
```
❌ Bad: Promising to do something and forgetting

✓ Good: Doing what you say you'll do

Example:
Agent: "I'll email you the notice within 5 minutes."
[Actually send the email within 5 minutes]
[Send follow-up: "I've sent the notice to your email. Please check your inbox and spam folder."]
```

#### Document Thoroughly
```
❌ Bad: Closing notes: "Helped user"

✓ Good: Closing notes: "User asked about payment status. Verified APEX12345. Provided tracking info for $237.50 payment mailed 01/15/2026. User satisfied. Emailed notice PDF. No further action needed."

Why it matters:
- Quality assurance reviewers can see what you did
- Next agent can pick up where you left off if user contacts again
- Demonstrates thoroughness
```

### 13.3 Common Quality Issues (and How to Avoid Them)

#### Issue: Not Reading Conversation History
**Problem**: Agent asks questions Lucy already asked

**Example**:
```
Lucy: "May I have your APEX ID?"
User: "APEX12345"
Lucy: "Thank you. Let me authenticate you."
[Agent joins]
Agent: "Hi, can you provide your APEX ID?" ❌

User (frustrated): "I already gave that to Lucy!"
```

**Solution**: Always read the full conversation history before sending your first message

#### Issue: Using Jargon
**Problem**: Agent uses technical terms user doesn't understand

**Example**:
```
Agent: "Your claim is in adjudication pending the final settlement distribution pro rata calculation." ❌

User: "What does that mean?"
```

**Solution**: Use plain language

```
Agent: "Your claim has been approved. We're currently calculating how much each person will receive. Payments should go out in March 2026." ✓
```

#### Issue: Not Confirming Understanding
**Problem**: Agent assumes user understood the answer

**Example**:
```
Agent: "Your payment was mailed January 15. You should receive it within 7-10 business days."
Agent: "Anything else I can help with?" ❌
[Didn't check if user understood or is satisfied]
```

**Solution**: Confirm understanding before moving on

```
Agent: "Your payment was mailed January 15. You should receive it within 7-10 business days, so by January 29 at the latest. Does that make sense? Do you have any questions about the payment?"
User: "Yes, that's clear. Thank you."
Agent: "Great! Anything else I can help with?" ✓
```

#### Issue: Rushing to Close
**Problem**: Agent ends conversation too quickly

**Example**:
```
User: "Okay, thanks."
Agent: "You're welcome!" [Immediately ends conversation] ❌
```

**Solution**: Give user opportunity to ask follow-up questions

```
User: "Okay, thanks."
Agent: "You're welcome! Is there anything else I can help you with today?"
[Wait for response]
User: "No, that's all."
Agent: "Perfect! Feel free to contact us if you have any other questions. Have a great day!"
[Now you can close] ✓
```

---

## 14. Training & Support

### 14.1 Getting Help

#### Technical Support
**For portal/system issues:**
- **Email**: it-support@apexclassaction.com
- **Phone**: (555) 100-2000
- **Teams**: @IT-HelpDesk
- **Response Time**: Within 30 minutes during business hours

**Common issues they handle:**
- Portal won't load
- WebSocket connection errors
- Permission/access issues
- Browser compatibility

#### Supervisor Escalation
**For customer issues beyond your authority:**
- **Teams**: @Supervisor-OnDuty
- **Phone**: Use "Escalate to Supervisor" button in portal
- **Response Time**: Within 5 minutes

**When to escalate:**
- User demands to speak to manager
- Issue requires approval you can't give
- Legal/compliance concern
- Abusive or threatening user

#### Portal Documentation
**Where to find help:**
- **This Guide**: http://portal.apexclassaction.com/docs/user-guide
- **FAQ**: http://portal.apexclassaction.com/faq
- **Video Tutorials**: http://portal.apexclassaction.com/training
- **Quick Reference**: [Appendix 16](#16-appendix-quick-reference)

#### Peer Learning Sessions
**When**: Weekly, Thursdays 2pm PST
**Where**: Teams meeting (link in calendar)
**What**: Share best practices, discuss challenging cases, Q&A

### 14.2 Continuing Education

#### Portal Updates Training
**Frequency**: As needed when new features are released
**Format**: 30-minute Teams meeting + hands-on practice
**Notification**: Email and Teams announcement 1 week in advance

**Recent Updates** (January 2026):
- Callback system improvements
- Document sharing via email
- Enhanced member profile view

#### Best Practices Workshops
**Frequency**: Monthly, first Wednesday 1pm PST
**Format**: 1-hour interactive workshop
**Topics**:
- Handling difficult conversations
- Improving resolution rates
- Using advanced search features
- Quality assurance tips

#### New Feature Announcements
**Channel**: Teams "Portal Updates" channel
**Subscribe**: Join channel for notifications
**Example announcement**:
```
📢 New Feature: Save Notes to Member Profile

You can now save your conversation notes directly to a member's Dynamics 365 profile.

How to use:
1. Type your note in the Context Panel
2. Click "Save Note to Profile"
3. Note is added to member's history

Benefits:
- Future agents can see what you documented
- Helps with repeat callers
- Improves customer experience

Try it out on your next conversation!
```

---

## 15. Frequently Asked Questions

### Portal Questions

**Q: How many conversations can I handle at once?**

**A**: The portal supports **one active conversation at a time**. Focus on giving each user your full attention. Once you close a conversation, you can join the next one from the pending queue.

---

**Q: Can I see all my past conversations?**

**A**: Yes, if you have been granted access. Navigate to http://portal.apexclassaction.com/agent/history to view conversations you've handled. You can filter by date, member ID, or search by keyword.

---

**Q: What if I accidentally close a conversation?**

**A**: Unfortunately, once a conversation is closed, you cannot reopen it. However, you can:
1. Use the Callback System to call the user back
2. View the transcript in "Past Conversations"
3. If user contacts again immediately, you'll see the conversation history

**Prevention tip**: The portal asks for confirmation before closing. Always double-check before clicking "End Conversation."

---

**Q: Can I transfer a conversation to another agent?**

**A**: Direct agent-to-agent transfer is not currently supported. Instead:
1. Use "Escalate to Supervisor" for supervisor assistance
2. Create a callback and assign it to a specific agent (if that feature is available)
3. In urgent cases, contact the other agent via Teams and coordinate handoff

---

### Process Questions

**Q: What if I can't resolve the issue?**

**A**: Follow this escalation process:

1. **Try all available tools first**:
   - Search documents
   - Check Dynamics 365
   - Review conversation history
   - Use internal knowledge base

2. **If you're stuck**:
   - Click "Escalate to Supervisor" in Quick Actions
   - Fill in escalation form with:
     - What you've tried
     - Why you can't resolve it
     - What user expects
   - Supervisor will join conversation or take over

3. **Tell the user**:
   ```
   Agent: "I need to bring in my supervisor who has additional authority to help with this. They'll join within 5 minutes. Is that okay?"
   ```

---

**Q: How do I know what Lucy already told the user?**

**A**: Review the **Conversation History Panel** (left side of portal). It shows:
- Every message Lucy sent
- Every message user sent
- Tool calls Lucy made (searches, document retrieval, etc.)
- System messages (authentication, errors, etc.)

**Tip**: Scroll to the top and read chronologically to understand the full context.

---

**Q: Can I edit Lucy's responses?**

**A**: No, you cannot edit Lucy's messages (they're historical). However, you can:
- **Clarify**: "Lucy mentioned X. What that means is..."
- **Correct**: "I see Lucy said Y. Let me provide you with the most current information..."
- **Expand**: "Lucy gave you the overview. Let me explain in more detail..."

---

### Technical Questions

**Q: What browsers are supported?**

**A**:
- ✓ **Google Chrome 90+** (recommended)
- ✓ **Microsoft Edge 90+**
- ✓ **Mozilla Firefox 88+**
- ❌ Internet Explorer (not supported)
- ⚠️ Safari on iOS (limited support - WebSocket issues)

**Always use the latest version** of your browser for best performance.

---

**Q: Do I need to install anything?**

**A**: No! The portal is **100% web-based**. You only need:
- A modern web browser
- Microsoft Teams (for notifications)
- Internet connection

**No downloads, no plugins, no extensions required.**

---

**Q: What if the portal is slow?**

**A**: Try these steps in order:

1. **Check your internet**:
   - Run speed test (minimum 5 Mbps)
   - Check VPN connection
   - Try another website to confirm internet works

2. **Refresh the portal**:
   - Press F5 (Windows) or Cmd+R (Mac)
   - Portal reloads and re-establishes connection

3. **Clear browser cache**:
   - Chrome: Ctrl+Shift+Delete → Clear cached images and files
   - Restart browser

4. **Report persistent slowness**:
   - Contact IT support
   - Provide: time, browser version, screenshot
   - They may identify server-side issues

---

**Q: Can I use the portal on my phone?**

**A**: The portal is designed for desktop/laptop use. While it may work on tablets, we **do not recommend using it on phones** because:
- Screen too small for three-panel layout
- Difficult to type long messages
- WebSocket connections may be unstable

**Use a computer for best experience.**

---

**Q: What happens if my internet disconnects during a conversation?**

**A**:
1. Portal shows "Disconnected" warning
2. Portal automatically tries to reconnect (up to 5 attempts)
3. If reconnection succeeds, conversation continues normally
4. If reconnection fails:
   - Call the user at the number in their profile
   - Apologize for the technical issue
   - Continue helping them over the phone
   - Complete the conversation via phone

**Your conversation is not lost** - it's saved in Azure Tables and can be resumed.

---

**Q: How do I report a bug?**

**A**: Use this process:

1. **Document the bug**:
   - What you were doing when it happened
   - Exact error message (screenshot)
   - Browser and version
   - Time and date
   - Steps to reproduce

2. **Report to IT**:
   - Email: it-support@apexclassaction.com
   - Include all documentation from step 1
   - Subject: "Portal Bug Report - [Brief Description]"

3. **Use workaround if available**:
   - IT may provide temporary workaround
   - Continue working while they fix the issue

---

### Member Information Questions

**Q: What if the user's information is wrong in the system?**

**A**: Help them update it:

1. **Identify what's wrong**:
   ```
   Agent: "I see we have your phone number as (555) 123-4567. Is that still correct?"
   User: "No, that's old. My new number is (555) 987-6543."
   ```

2. **Update in Dynamics 365** (if you have access):
   - Navigate to member profile
   - Edit the field
   - Save changes

3. **Or create a note for admin team**:
   - Click "Save Note to Profile"
   - Note: "User reports phone number should be (555) 987-6543, not (555) 123-4567 currently on file. Please update."

4. **Confirm with user**:
   ```
   Agent: "I've updated your phone number to (555) 987-6543. You should see the change reflected in 24 hours."
   ```

---

**Q: Can I access information for family members?**

**A**: **No, not without proper authorization.**

**Privacy rules**:
- You can only access information for the authenticated member
- Even if caller says "I'm calling for my spouse/parent/child," you need to authenticate the actual member or have proof of authorization (power of attorney, etc.)

**Example**:
```
User: "I'm calling about my mom's claim. Her name is Jane Doe."

Agent: "I'd be happy to help. However, for privacy reasons, I need to speak directly with Jane Doe, or you'll need to provide documentation showing you're authorized to discuss her account. Can you put Jane on the line, or do you have a power of attorney I can verify?"
```

---

## 16. Appendix: Quick Reference

### Keyboard Shortcuts

**Message Composition**:
- `Enter` - Send message (default)
- `Shift+Enter` - New line in message
- `Ctrl+Enter` - Send message (alternate)
- `Esc` - Clear message draft

**Navigation**:
- `Ctrl+1` - Focus conversation history
- `Ctrl+2` - Focus active chat (message input)
- `Ctrl+3` - Focus context panel
- `Alt+H` - Jump to conversation history
- `Alt+M` - Focus message input
- `Alt+I` - Open member info

**Actions**:
- `Ctrl+N` - Save note to profile
- `Ctrl+D` - Download transcript
- `Ctrl+E` - End conversation
- `Ctrl+/` - Show keyboard shortcuts help

---

### Status Indicators

**Connection Status** (Top right of portal):

| Indicator | Meaning | What to Do |
|-----------|---------|------------|
| 🟢 Green dot | Connected and active | Normal - continue working |
| 🟡 Yellow dot | Connection unstable | Wait, portal is trying to reconnect |
| 🔴 Red dot | Disconnected | Refresh page or wait for auto-reconnect |
| 🔵 Blue dot | You are typing | Normal - user sees "Agent is typing..." |

**User Status** (In conversation):

| Indicator | Meaning |
|-----------|---------|
| "User is typing..." | User is composing a message |
| "User is idle" | User hasn't typed in 2+ minutes |
| "User disconnected" | User closed browser or lost connection |
| Last seen: 5 minutes ago | User hasn't sent message in 5 minutes |

---

### Common Actions Quick Guide

**Joining a Conversation**:
1. Receive Teams notification
2. Click "Join Conversation NOW"
3. Portal opens automatically
4. Read conversation history
5. Send first message within 30 seconds

**Accessing Member Information**:
1. Look at Context Panel (right side)
2. Authenticated members show full info
3. Non-authenticated show limited info
4. Click "View Full Profile" for details

**Viewing a Document**:
1. Find document in Context Panel → Documents
2. Click "View" to open in new tab
3. Or click "Download" to save locally

**Ending a Conversation**:
1. Confirm user is satisfied: "Anything else I can help with?"
2. Wait for user confirmation: "No, that's all"
3. Click "End Conversation" button
4. Add closing note (required)
5. Click "Confirm End"

**Creating a Callback**:
1. Click "Create Callback" in Quick Actions
2. Fill in user's phone number
3. Add reason/notes
4. Select priority
5. Click "Save"

**Escalating to Supervisor**:
1. Click "Escalate to Supervisor"
2. Fill in escalation form
3. Explain what you tried
4. Explain why you need supervisor
5. Click "Submit"
6. Tell user: "My supervisor will join within 5 minutes"

---

### Important Links

**Portal URLs**:
- **Agent Portal Dashboard**: http://portal.apexclassaction.com/agent/portal
- **Pending Callbacks**: http://portal.apexclassaction.com/agent/callbacks
- **Your Conversation History**: http://portal.apexclassaction.com/agent/history
- **Metrics Dashboard**: http://portal.apexclassaction.com/agent/dashboard

**Documentation**:
- **This Guide**: http://portal.apexclassaction.com/docs/user-guide
- **FAQ**: http://portal.apexclassaction.com/faq
- **Video Tutorials**: http://portal.apexclassaction.com/training

**Support**:
- **IT Support Email**: it-support@apexclassaction.com
- **IT Support Phone**: (555) 100-2000
- **Supervisor Teams**: @Supervisor-OnDuty
- **Portal Updates Channel**: Teams → "Portal Updates"

---

### Troubleshooting Cheat Sheet

| Problem | Quick Fix |
|---------|-----------|
| Can't join conversation | Check pop-up blocker, refresh Teams, try different browser |
| No conversation history | Wait 10 seconds, refresh page, continue without history if urgent |
| WebSocket disconnected | Wait for auto-reconnect, refresh page if it fails |
| User not responding | Wait 2-3 minutes, send gentle follow-up, wait another 2 minutes |
| PDF won't load | Try download instead of view, search by alternative method |
| Portal is slow | Check internet, refresh page, clear browser cache |
| Error message | Take screenshot, note conversation ID, contact IT support |

---

### Professional Response Templates

**First Message (General)**:
```
Hi [Name], I'm [Your Name], an APEX representative. I can see that [acknowledge their issue]. I've reviewed your conversation with Lucy, so you don't need to repeat anything. [Next step].
```

**First Message (User Requested Human)**:
```
Hi [Name], I'm [Your Name], an APEX representative. I can see you asked to speak with a person. I've reviewed your conversation with Lucy about [topic]. Let me help you with that right now.
```

**Acknowledging Frustration**:
```
I completely understand your frustration. [Validate their concern]. I'm here to get you answers right now. Let me [specific action].
```

**Setting Expectations**:
```
Let me [action]. This will take about [time]. Please wait just a moment.
```

**Confirming Resolution**:
```
I've provided you with [summary of what you did]. Is there anything else I can help you with today?
```

**Closing**:
```
You're very welcome! If you have any other questions in the future, feel free to contact us anytime. Have a great day!
```

**Escalating**:
```
I need to bring in my supervisor who has additional authority to help with this. They'll join within 5 minutes. Is that okay?
```

**Technical Issue**:
```
I'm experiencing a technical issue with [system]. Let me [workaround]. I apologize for the inconvenience.
```

---

## 17. Video Tutorial Script

**Video Tutorial: Your First Handoff**

**Total Duration**: ~2.5 minutes

---

### Scene 1: Receiving Notification (30 seconds)

**[Screen Recording: Teams desktop application]**

**Voiceover**:
> "When Lucy AI escalates a conversation, you'll receive a notification in Microsoft Teams. Let's see what that looks like."

**[Visual: Teams notification banner appears in bottom right]**

**[Visual: Teams "Lucy Escalations" channel shows new message]**

**[Camera zooms in on Adaptive Card]**

**Voiceover**:
> "The notification shows you key information: the member's APEX ID, the reason for escalation, and how long they've been waiting. You have 4 minutes to join before the callback system activates."

**[Visual: Highlight the following on card]**
- Member ID: APEX12345
- Reason: "User needs help with payment status"
- Time: 10:30 AM
- 4-minute timer graphic

**[Visual: Cursor hovers over "Join Conversation NOW" button]**

**Voiceover**:
> "Click the red 'Join Conversation NOW' button to open the portal."

**[Visual: Cursor clicks button]**

---

### Scene 2: Portal Opens (45 seconds)

**[Screen Recording: Browser opens to portal]**

**[Visual: Loading screen → Portal interface appears]**

**Voiceover**:
> "The portal opens in your browser and automatically loads the conversation."

**[Visual: Three-panel layout appears]**

**Voiceover**:
> "The portal has three main sections:"

**[Visual: Highlight left panel]**
> "On the left, you see the full conversation history between Lucy and the user."

**[Visual: Highlight center panel]**
> "In the center is your active chat area where you'll communicate with the member."

**[Visual: Highlight right panel]**
> "On the right is the context panel showing member information and documents."

**[Visual: Scroll through conversation history]**

**Voiceover**:
> "Before sending your first message, read through the conversation history. See what Lucy already discussed with the user."

**[Visual: Highlight specific messages in history]**
- Lucy: "May I have your APEX ID?"
- User: "APEX12345"
- Lucy: "Let me search for your payment information..."

**Voiceover**:
> "You can see Lucy already collected the user's APEX ID and was searching for payment information."

**[Visual: Green "Connected" indicator appears in top right]**

**Voiceover**:
> "The green indicator shows you're connected and ready to chat."

---

### Scene 3: Communicating (1 minute)

**[Visual: Cursor clicks in message input box]**

**Voiceover**:
> "Now you're ready to send your first message. Always introduce yourself and acknowledge what the user needs."

**[Visual: Typing animation]**

**Text appears**:
```
Hi John, I'm Sarah, an APEX representative. I can see you're asking about your payment status. Lucy already looked up your information, so I have your details. Let me check the latest update on your payment right now.
```

**[Visual: Cursor clicks "Send" button]**

**[Visual: Message appears in chat with green background (agent message)]**

**Voiceover**:
> "Your message is sent to the user. They see it immediately in their chat with Lucy."

**[Visual: Simulated user screen showing the message arriving]**

**[Visual: Back to agent portal - "User is typing..." appears]**

**Voiceover**:
> "You'll see when the user is typing a response."

**[Visual: User message appears in chat with gray background]**

**User message**:
```
Thank you! I've been waiting for weeks.
```

**[Visual: Agent typing response]**

**Agent message**:
```
I understand. Let me pull up your account right now. Give me just 30 seconds.
```

**[Visual: Agent navigates to Context Panel → Member Information]**

**Voiceover**:
> "You can access member information in the context panel while chatting."

**[Visual: Highlight member details]**
- Name: John Doe
- APEX ID: APEX12345
- Settlement: ABC Company (2024)
- Payment: $237.50 - Mailed 01/15/2026

**[Visual: Agent types response]**

**Agent message**:
```
Good news! I've found your payment information. Your check for $237.50 was mailed on January 15, 2026. USPS tracking shows it should arrive by January 29. If you don't receive it by February 1, contact us and we'll issue a replacement immediately. Would you like me to email you the tracking information?
```

**[Visual: User response]**

**User message**:
```
That would be great, thank you!
```

**Voiceover**:
> "Continue the conversation until the user's issue is fully resolved."

---

### Scene 4: Closing (30 seconds)

**[Visual: Agent types final confirmation]**

**Agent message**:
```
I've sent the tracking information to john.doe@email.com. You should receive it within a few minutes. Is there anything else I can help you with today?
```

**[Visual: User response]**

**User message**:
```
No, that's everything. Thank you so much!
```

**[Visual: Agent types closing]**

**Agent message**:
```
You're very welcome! If you have any other questions in the future, feel free to contact us anytime. Have a great day!
```

**[Visual: Cursor moves to "End Conversation" button]**

**Voiceover**:
> "Once the user confirms they're satisfied, click 'End Conversation'."

**[Visual: Click "End Conversation" → Confirmation dialog appears]**

**Voiceover**:
> "Add a closing note for quality assurance."

**[Visual: Type closing note]**

**Closing note**:
```
User satisfied. Provided payment tracking info ($237.50 mailed 01/15/2026). Emailed tracking details. No further action needed.
```

**[Visual: Click "End Conversation" button in dialog]**

**[Visual: Confirmation message appears]**

**Confirmation message**:
```
✓ Conversation Ended
Transcript saved. Redirecting to portal dashboard...
```

**[Visual: Fade to portal dashboard showing pending conversations]**

**Voiceover**:
> "Great job! You've successfully handled your first escalation. The conversation is archived, and you're ready to help the next member."

**[Visual: Text overlay]**

**Text**:
```
For more help:
• User Guide: portal.apexclassaction.com/docs/user-guide
• FAQ: portal.apexclassaction.com/faq
• Support: it-support@apexclassaction.com
```

**[Fade to black]**

**[End of video]**

---

**End of Lucy Agent Portal User Guide**

**Document Version**: 1.0
**Last Updated**: 2026-01-25
**Maintained By**: Documentation Team
**Questions?** Contact: training@apexclassaction.com
