#property indicator_chart_window
#property indicator_plots 0
#property indicator_buffers 0
#property version "1.10"
#property description "Position Snapshot Indicator - exports MT5 positions to JSON"

#define SNAPSHOT_FILE_A "auto_trade_positions_a.json"
#define SNAPSHOT_FILE_B "auto_trade_positions_b.json"
#define SNAPSHOT_INTERVAL 1
#define SNAPSHOT_SCHEMA 1

long g_sequence = 0;
bool g_timer_active = false;

int OnInit()
  {
   if(!EventSetTimer(SNAPSHOT_INTERVAL))
      return(INIT_FAILED);
   g_timer_active = true;
   WriteSnapshot();
   return(INIT_SUCCEEDED);
  }

void OnDeinit(const int reason)
  {
   if(g_timer_active)
     {
      EventKillTimer();
      g_timer_active = false;
     }
  }

void OnTimer()
  {
   WriteSnapshot();
  }

bool WriteSnapshot()
  {
   g_sequence++;
   int total_positions = PositionsTotal();
   int position_count = 0;
   string rows = "";

   for(int index = 0; index < total_positions; index++)
     {
      ulong ticket = PositionGetTicket(index);
      if(ticket == 0)
         continue;

      string side = "SELL";
      if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
         side = "BUY";

      if(position_count > 0)
         rows += ",\n    ";

      rows += "{\"ticket\": " + Num64((long)ticket)
            + ", \"symbol\": \"" + EscapeJson(PositionGetString(POSITION_SYMBOL))
            + "\", \"type\": \"" + side
            + "\", \"volume\": " + Num(PositionGetDouble(POSITION_VOLUME))
            + ", \"price_open\": " + Num(PositionGetDouble(POSITION_PRICE_OPEN))
            + ", \"sl\": " + Num(PositionGetDouble(POSITION_SL))
            + ", \"tp\": " + Num(PositionGetDouble(POSITION_TP))
            + ", \"profit\": " + Num(PositionGetDouble(POSITION_PROFIT))
            + ", \"magic\": " + Num64((long)PositionGetInteger(POSITION_MAGIC))
            + ", \"opened_at\": \""
            + UtcStamp((datetime)PositionGetInteger(POSITION_TIME)) + "\"}";
      position_count++;
     }

   string document = "";
   document += "{\n";
   document += "  \"schema\": " + IntegerToString(SNAPSHOT_SCHEMA) + ",\n";
   document += "  \"sequence\": " + Num64(g_sequence) + ",\n";
   document += "  \"complete\": true,\n";
   document += "  \"written_at\": \"" + UtcStamp() + "\",\n";
   document += "  \"account\": " + Num64((long)AccountInfoInteger(ACCOUNT_LOGIN)) + ",\n";
   document += "  \"server\": \"" + EscapeJson(AccountInfoString(ACCOUNT_SERVER)) + "\",\n";
   document += "  \"terminal_build\": " + IntegerToString((int)TerminalInfoInteger(TERMINAL_BUILD)) + ",\n";
   document += "  \"positions\": [";
   if(position_count > 0)
      document += "\n    " + rows + "\n  ";
   document += "]\n}\n";
   return WriteAlternating(document);
  }

bool WriteAlternating(const string document)
  {
   bool to_a = ((g_sequence % 2) == 0);
   string target = to_a ? SNAPSHOT_FILE_A : SNAPSHOT_FILE_B;
   string stale = to_a ? SNAPSHOT_FILE_B : SNAPSHOT_FILE_A;
   int flags = FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_SHARE_READ | FILE_SHARE_WRITE;
   int handle = FileOpen(target, flags);
   if(handle == INVALID_HANDLE)
      return false;

   uint written_chars = FileWriteString(handle, document);
   FileClose(handle);
   if(written_chars != (uint)StringLen(document))
      return false;

   FileDelete(stale);
   return true;
  }

int OnCalculate(
   const int rates_total,
   const int prev_calculated,
   const datetime &time[],
   const double &open[],
   const double &high[],
   const double &low[],
   const double &close[],
   const long &tick_volume[],
   const long &volume[],
   const int &spread[]
)
  {
   return(rates_total);
  }

string UtcStamp(const datetime when = 0)
  {
   datetime value = (when == 0) ? TimeGMT() : when;
   MqlDateTime parts;
   if(!TimeToStruct(value, parts))
      return "1970-01-01T00:00:00Z";
   return IntegerToString(parts.year) + "-" + Pad2(parts.mon) + "-" + Pad2(parts.day)
        + "T" + Pad2(parts.hour) + ":" + Pad2(parts.min) + ":" + Pad2(parts.sec) + "Z";
  }

string Pad2(const int value)
  {
   if(value < 10)
      return "0" + IntegerToString(value);
   return IntegerToString(value);
  }

string Num(const double value)
  {
   return DoubleToString(value, 8);
  }

string Num64(const long value)
  {
   return StringFormat("%I64d", value);
  }

string EscapeJson(const string value)
  {
   string result = value;
   StringReplace(result, "\\", "\\\\");
   StringReplace(result, "\"", "\\\"");
   StringReplace(result, "\r", "\\r");
   StringReplace(result, "\n", "\\n");
   StringReplace(result, "\t", "\\t");
   return result;
  }
