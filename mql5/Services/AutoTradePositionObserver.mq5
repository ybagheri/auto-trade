//+------------------------------------------------------------------+
//|                                    AutoTradePositionObserver.mq5   |
//|                                                                  |
//|  Read-only position observer for the auto-trade bridge.          |
//|                                                                  |
//|  SAFETY: this program NEVER sends, modifies, closes or cancels   |
//|  any order. It contains no OrderSend and no trade request call   |
//|  of any kind. Its only job is to report what the terminal        |
//|  already shows, so the external application can verify execution |
//|  independently of the desktop UI that produced the request.      |
//|                                                                  |
//|  The snapshot alternates between two files and the previous one |
//|  is deleted only after the new one is fully written, so a reader |
//|  never observes a half written snapshot.                         |
//+------------------------------------------------------------------+
#property version   "1.00"
#property description "Read-only JSON snapshot of open positions for external verification."

#define SNAPSHOT_FILE_A   "auto_trade_positions_a.json"
#define SNAPSHOT_FILE_B   "auto_trade_positions_b.json"
#define DIAGNOSTIC_FILE   "auto_trade_observer.log"
#define SNAPSHOT_INTERVAL 1
#define SNAPSHOT_SCHEMA   1

long g_sequence = 0;
int  g_timer    = 0;

//+------------------------------------------------------------------+
//| Start the observation timer.                                     |
//+------------------------------------------------------------------+
int OnInit()
  {
   Trace("OnInit entered");

   g_timer = EventSetTimer(SNAPSHOT_INTERVAL);
   if(g_timer == 0)
     {
      int first_error = GetLastError();
      Trace("EventSetTimer failed, error " + IntegerToString(first_error)
            + "; trying EventSetMillisecondTimer");
      g_timer = EventSetMillisecondTimer(SNAPSHOT_INTERVAL * 1000);
      if(g_timer == 0)
        {
         Trace("EventSetMillisecondTimer failed too, error " + IntegerToString(GetLastError())
               + "; running one-shot snapshots only");
        }
     }

   WriteSnapshot();
   Trace("OnInit complete, timer=" + IntegerToString(g_timer));
   return(INIT_SUCCEEDED);
  }

//+------------------------------------------------------------------+
//| Append one line to the diagnostic file.                          |
//|                                                                  |
//| MQL5 program logging can be switched off in terminal options, so |
//| the observer keeps its own trail next to the snapshots.         |
//+------------------------------------------------------------------+
void Trace(const string message)
  {
   int handle = FileOpen(DIAGNOSTIC_FILE,
                         FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ);
   if(handle == INVALID_HANDLE)
      return;
   FileSeek(handle, 0, SEEK_END);
   FileWriteString(handle, UtcStamp() + " " + message + "\n");
   FileClose(handle);
  }

//+------------------------------------------------------------------+
//| Stop the observation timer.                                      |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
  {
   if(g_timer != 0)
      EventKillTimer();
   Trace("OnDeinit, reason " + IntegerToString(reason)
         + ", snapshots written " + Num64(g_sequence));
  }

//+------------------------------------------------------------------+
//| Services receive no ticks; all work happens on the timer.        |
//+------------------------------------------------------------------+
void OnTick()
  {
  }

//+------------------------------------------------------------------+
//| Periodic snapshot.                                               |
//+------------------------------------------------------------------+
void OnTimer()
  {
   WriteSnapshot();
  }

//+------------------------------------------------------------------+
//| Serialize the current open positions to a JSON document.         |
//+------------------------------------------------------------------+
bool WriteSnapshot()
  {
   g_sequence++;

   int total    = PositionsTotal();
   int position = 0;
   string rows  = "";

   for(int index = 0; index < total; index++)
     {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0)
         continue;

      string side = "SELL";
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         side = "BUY";

      if(position > 0)
         rows += ",\n    ";

      rows += "{\"ticket\": " + Num64((long)ticket)
            + ", \"symbol\": \"" + PositionGetString(POSITION_SYMBOL)
            + "\", \"type\": \"" + side
            + "\", \"volume\": " + Num(PositionGetDouble(POSITION_VOLUME))
            + ", \"price_open\": " + Num(PositionGetDouble(POSITION_PRICE_OPEN))
            + ", \"sl\": " + Num(PositionGetDouble(POSITION_SL))
            + ", \"tp\": " + Num(PositionGetDouble(POSITION_TP))
            + ", \"profit\": " + Num(PositionGetDouble(POSITION_PROFIT))
            + ", \"magic\": " + Num64((long)PositionGetInteger(POSITION_MAGIC))
            + ", \"opened_at\": \""
            + UtcStamp((datetime)PositionGetInteger(POSITION_TIME)) + "\"}";
      position++;
     }

   string document = "";
   document += "{\n";
   document += "  \"schema\": " + IntegerToString(SNAPSHOT_SCHEMA) + ",\n";
   document += "  \"sequence\": " + Num64(g_sequence) + ",\n";
   document += "  \"complete\": true,\n";
   document += "  \"written_at\": \"" + UtcStamp() + "\",\n";
   document += "  \"account\": "
            + Num64((long)AccountInfoInteger(ACCOUNT_LOGIN)) + ",\n";
   document += "  \"server\": \"" + AccountInfoString(ACCOUNT_SERVER) + "\",\n";
   document += "  \"terminal_build\": "
            + IntegerToString(TerminalInfoInteger(TERMINAL_BUILD)) + ",\n";
   document += "  \"positions\": [";
   if(position > 0)
      document += "\n    " + rows + "\n  ";
   document += "]\n}\n";

   return WriteAlternating(document);
  }

//+------------------------------------------------------------------+
//| Write the document, then remove the previous file.               |
//|                                                                  |
//| Alternating the target guarantees a reader finds at most one     |
//| file, and that file is only visible once it is complete.         |
//+------------------------------------------------------------------+
bool WriteAlternating(const string document)
  {
   bool to_a     = ((g_sequence % 2) == 0);
   string target = to_a ? SNAPSHOT_FILE_A : SNAPSHOT_FILE_B;
   string stale  = to_a ? SNAPSHOT_FILE_B : SNAPSHOT_FILE_A;

   int flags  = FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE;
   int handle = FileOpen(target, flags);
   if(handle == INVALID_HANDLE)
     {
      Trace("FileOpen(" + target + ") failed, error " + IntegerToString(GetLastError()));
      return false;
     }

   int expected = StringLen(document);
   int actual   = (int)FileWriteString(handle, document);
   if(actual != expected)
     {
      Trace("short write to " + target + ": " + IntegerToString(actual)
            + " of " + IntegerToString(expected));
      FileClose(handle);
      return false;
     }
   FileClose(handle);

   FileDelete(stale);
   return true;
  }

//+------------------------------------------------------------------+
//| UTC timestamp in ISO 8601 form, or the current UTC time when     |
//| 'when' is 0.                                                     |
//|                                                                  |
//| Dashes are required: the reader parses this with fromisoformat,  |
//| which does not accept MQL5's usual dotted date form.             |
//+------------------------------------------------------------------+
string UtcStamp(const datetime when = 0)
  {
   datetime value = (when == 0) ? TimeGMT() : when;
   MqlDateTime parts;
   if(!TimeToStruct(value, parts))
      return "1970-01-01T00:00:00Z";

   string out = IntegerToString(parts.year) + "-";
   out += Pad2(parts.mon) + "-";
   out += Pad2(parts.day) + "T";
   out += Pad2(parts.hour) + ":";
   out += Pad2(parts.min) + ":";
   out += Pad2(parts.sec) + "Z";
   return out;
  }

//+------------------------------------------------------------------+
//| Two digit zero padded value.                                     |
//+------------------------------------------------------------------+
string Pad2(const int value)
  {
   if(value < 10)
      return "0" + IntegerToString(value);
   return IntegerToString(value);
  }

//+------------------------------------------------------------------+
//| Fixed precision, locale independent number.                      |
//+------------------------------------------------------------------+
string Num(const double value)
  {
   return DoubleToString(value, 8);
  }

//+------------------------------------------------------------------+
//| 64 bit integer as text.                                          |
//+------------------------------------------------------------------+
string Num64(const long value)
  {
   return StringFormat("%I64d", value);
  }
//+------------------------------------------------------------------+
